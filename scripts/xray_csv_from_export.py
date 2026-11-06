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

def csv_cell(value: Any) -> str:
    """
    Make a value safe for Xray CSV import.

    Important:
    - No embedded line breaks
    - No tabs
    - No repeated whitespace
    - Preserve non-ASCII characters
    """
    text = clean_text(value)
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def required_action(value: Any) -> str:
    """
    Xray requires Action.
    If a converted step has only an expected result, provide a generic action.
    """
    action = csv_cell(value)
    return action if action else "Verify expected result"


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
        source_key = csv_cell(metadata.get("key"))

        if not source_key:
            continue

        summary = csv_cell(metadata.get("summary"))
        if summary_prefix:
            summary = csv_cell(f"{summary_prefix}{summary}")

        if not summary:
            continue

        description = csv_cell(doc.get("raw_content", {}).get("description")) or csv_cell(doc.get("content"))
        labels = csv_cell(normalize_labels(metadata.get("labels")))

        step_source, steps = extract_steps(doc)

        if not steps and include_empty_tests:
            steps = [{"action": "Manual test step", "data": "", "expected": ""}]

        for step in steps:
            action = required_action(step.get("action"))
            data = csv_cell(step.get("data"))
            expected = csv_cell(step.get("expected"))

            if not action:
                continue

            rows.append(
                {
                    "Test Case Identifier": source_key,
                    "Summary": summary,
                    "Description": description,
                    "Test Type": DEFAULT_TEST_TYPE,
                    "Action": action,
                    "Data": data,
                    "Expected Result": expected,
                    "Labels": labels,
                    "Source Step Field": csv_cell(step_source),
                }
            )

    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "Test Case Identifier",
        "Summary",
        "Description",
        "Test Type",
        "Action",
        "Data",
        "Expected Result",
        "Labels",
        "Source Step Field",
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter=",",
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
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
