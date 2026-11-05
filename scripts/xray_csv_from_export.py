#!/usr/bin/env python3
"""
Convert Jira RAG JSON export to Xray CSV Bulk Import format.

Behavior:
- Reads a JSON export produced by jira-api-exporter.
- Filters only issues where metadata.issuetype == "Test".
- Exports only Manual tests.
- Converts these configured custom fields into manual test steps:
  - manual_test_steps
  - cucumber_scenario
  - generic_test_definition
- Allows adding a prefix to the Jira ticket summary.

Example:
  python xray_csv_from_export.py \
    --input jira-exports/xray_tests.json \
    --output xray_manual_import.csv \
    --summary-prefix "[MIGRATED] "

The generated CSV is intended to be mapped in the Xray Bulk Test Case Importer.
"""

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_TEST_TYPE = "Manual"


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Input JSON must be a list of exported Jira documents.")

    return data


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def get_custom_field_value(doc: dict[str, Any], alias: str) -> str:
    """
    Reads a custom field value defensively from both expected locations:

    metadata.custom_fields.<alias>.value
    raw_content.custom_fields.<alias>.value

    This keeps the converter independent from small export format changes.
    """
    metadata_fields = doc.get("metadata", {}).get("custom_fields", {})
    raw_fields = doc.get("raw_content", {}).get("custom_fields", {})

    for source in (metadata_fields, raw_fields):
        field = source.get(alias)
        if isinstance(field, dict):
            value = clean_text(field.get("value"))
            if value:
                return value
        elif isinstance(field, str):
            value = clean_text(field)
            if value:
                return value

    return ""


def normalize_labels(labels: Any) -> str:
    if not labels:
        return ""

    if isinstance(labels, list):
        return ",".join(str(label).strip() for label in labels if str(label).strip())

    return str(labels).strip()


def is_test_issue(doc: dict[str, Any]) -> bool:
    issuetype = clean_text(doc.get("metadata", {}).get("issuetype"))
    return issuetype.lower() == "test"


def parse_manual_steps(value: str) -> list[dict[str, str]]:
    """
    Converts manual step content into Xray manual step rows.

    Supported generic formats:
    - Plain lines
    - Bullet lists
    - Numbered lists
    - Simple table-like lines with separators:
      action | data | expected
      action ; data ; expected
      action, data, expected

    If no structure is detected, each non-empty line becomes one Action.
    """
    value = clean_text(value)
    if not value:
        return []

    steps: list[dict[str, str]] = []

    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue

        # Remove common bullets / numbering.
        line = re.sub(r"^\s*[-*]\s+", "", line)
        line = re.sub(r"^\s*\d+[\.)]\s+", "", line)

        parts = split_step_line(line)

        steps.append(
            {
                "action": parts[0],
                "data": parts[1] if len(parts) > 1 else "",
                "expected": parts[2] if len(parts) > 2 else "",
            }
        )

    return steps


def split_step_line(line: str) -> list[str]:
    """
    Splits a step line into action/data/expected if a simple delimiter is present.
    Keeps the function conservative to avoid destroying natural language text.
    """
    for delimiter in ("|", ";"):
        if delimiter in line:
            parts = [part.strip() for part in line.split(delimiter)]
            parts = [part for part in parts if part]
            if len(parts) >= 2:
                return parts[:3]

    return [line]


def parse_gherkin_to_manual_steps(value: str) -> list[dict[str, str]]:
    """
    Converts Gherkin/Cucumber scenario text to manual steps.

    Mapping:
    - Given / When / And / But -> Action
    - Then -> Expected Result
    - Other relevant lines become Action
    """
    value = clean_text(value)
    if not value:
        return []

    steps: list[dict[str, str]] = []

    ignored_prefixes = (
        "feature:",
        "scenario:",
        "scenario outline:",
        "background:",
        "examples:",
        "@",
    )

    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()

        if lower.startswith(ignored_prefixes):
            continue

        # Skip Gherkin example tables.
        if line.startswith("|") and line.endswith("|"):
            continue

        keyword_match = re.match(r"^(given|when|then|and|but)\b\s*(.*)$", line, re.IGNORECASE)

        if keyword_match:
            keyword = keyword_match.group(1).lower()
            text = keyword_match.group(2).strip() or line

            if keyword == "then":
                steps.append(
                    {
                        "action": "",
                        "data": "",
                        "expected": text,
                    }
                )
            else:
                steps.append(
                    {
                        "action": text,
                        "data": "",
                        "expected": "",
                    }
                )
        else:
            steps.append(
                {
                    "action": line,
                    "data": "",
                    "expected": "",
                }
            )

    return compact_expected_only_steps(steps)


def compact_expected_only_steps(steps: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    If a Then-step follows an action step, attach it as the expected result
    to the previous action. This produces cleaner Manual Test Steps.
    """
    compacted: list[dict[str, str]] = []

    for step in steps:
        action = clean_text(step.get("action"))
        data = clean_text(step.get("data"))
        expected = clean_text(step.get("expected"))

        if expected and not action and compacted:
            previous = compacted[-1]
            previous_expected = clean_text(previous.get("expected"))
            previous["expected"] = f"{previous_expected}\n{expected}" if previous_expected else expected
            continue

        compacted.append(
            {
                "action": action,
                "data": data,
                "expected": expected,
            }
        )

    return compacted


def parse_generic_definition(value: str) -> list[dict[str, str]]:
    """
    Converts a generic test definition into manual steps.
    The converter is intentionally conservative:
    each non-empty line becomes one manual Action.
    """
    return parse_manual_steps(value)


def extract_steps(doc: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """
    Selects the best available source for Manual Test Steps.

    Priority:
    1. manual_test_steps
    2. cucumber_scenario converted to manual steps
    3. generic_test_definition converted to manual steps
    4. content fallback as one manual step
    """
    manual = get_custom_field_value(doc, "manual_test_steps")
    if manual:
        return "manual_test_steps", parse_manual_steps(manual)

    cucumber = get_custom_field_value(doc, "cucumber_scenario")
    if cucumber:
        return "cucumber_scenario", parse_gherkin_to_manual_steps(cucumber)

    generic = get_custom_field_value(doc, "generic_test_definition")
    if generic:
        return "generic_test_definition", parse_generic_definition(generic)

    content = clean_text(doc.get("content"))
    if content:
        return "content", [{"action": content, "data": "", "expected": ""}]

    return "empty", []


def build_rows(
    documents: list[dict[str, Any]],
    summary_prefix: str,
    include_empty_tests: bool,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for doc in documents:
        if not is_test_issue(doc):
            continue

        metadata = doc.get("metadata", {})
        source_key = clean_text(metadata.get("key"))
        summary = clean_text(metadata.get("summary"))

        if summary_prefix:
            summary = f"{summary_prefix}{summary}"

        description = clean_text(doc.get("raw_content", {}).get("description")) or clean_text(doc.get("content"))

        labels = normalize_labels(metadata.get("labels"))

        step_source, steps = extract_steps(doc)

        if not steps and include_empty_tests:
            steps = [{"action": "", "data": "", "expected": ""}]

        for step_index, step in enumerate(steps, start=1):
            rows.append(
                {
                    "Summary": summary,
                    "Description": description if step_index == 1 else "",
                    "Test Type": DEFAULT_TEST_TYPE,
                    "Manual Test Step Action": clean_text(step.get("action")),
                    "Manual Test Step Data": clean_text(step.get("data")),
                    "Manual Test Step Expected Result": clean_text(step.get("expected")),
                    "Source Issue Key": source_key,
                    "Source Step Field": step_source,
                    "Labels": labels,
                }
            )

    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "Summary",
        "Description",
        "Test Type",
        "Manual Test Step Action",
        "Manual Test Step Data",
        "Manual Test Step Expected Result",
        "Source Issue Key",
        "Source Step Field",
        "Labels",
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter=",",
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Jira RAG JSON export to Xray Manual Test CSV.")

    parser.add_argument(
        "--input",
        required=True,
        help="Path to Jira RAG JSON export.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output CSV file.",
    )
    parser.add_argument(
        "--summary-prefix",
        default="",
        help="Optional prefix added to every test summary.",
    )
    parser.add_argument(
        "--include-empty-tests",
        action="store_true",
        help="Also export Test issues without any step content as empty Manual tests.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    documents = load_json(input_path)
    rows = build_rows(
        documents=documents,
        summary_prefix=args.summary_prefix,
        include_empty_tests=args.include_empty_tests,
    )
    write_csv(output_path, rows)

    print(f"Read documents: {len(documents)}")
    print(f"Written CSV rows: {len(rows)}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
