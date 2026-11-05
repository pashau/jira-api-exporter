"""Export-Logik: Issues → RAG-optimiertes JSON."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cleaner import TextCleaner
from .client import JiraClient

logger = logging.getLogger(__name__)

DEFAULT_EPIC_LINK_FIELD = "customfield_10100"


def _extract_epic_link(fields: Dict[str, Any], epic_link_field: str) -> str:
    """Liest den Epic Link (Custom Field) und gibt den Key des Epics zurück, sonst ''."""
    value = fields.get(epic_link_field)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return value.get("key") or value.get("value") or ""
    return ""


def _extract_issue_links(fields: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Wandelt 'issuelinks' in eine flache Liste um. Jeder Link hat in Jira entweder ein
    'outwardIssue' (z.B. 'blocks') oder ein 'inwardIssue' (z.B. 'is blocked by').
    """
    links: List[Dict[str, str]] = []
    for link in fields.get("issuelinks") or []:
        link_type = link.get("type") or {}

        if "outwardIssue" in link:
            direction, target, relation = "outward", link["outwardIssue"], link_type.get("outward", "")
        elif "inwardIssue" in link:
            direction, target, relation = "inward", link["inwardIssue"], link_type.get("inward", "")
        else:
            continue

        target_fields = target.get("fields") or {}
        links.append(
            {
                "type": link_type.get("name", ""),
                "direction": direction,
                "relation": relation,
                "key": target.get("key", ""),
                "summary": TextCleaner.clean(target_fields.get("summary", "")),
                "status": (target_fields.get("status") or {}).get("name", ""),
                "issuetype": (target_fields.get("issuetype") or {}).get("name", ""),
            }
        )
    return links


def _label_from_alias(alias: str) -> str:
    """Erzeugt aus einem technischen Alias ein lesbares Label."""
    label = alias.replace("_", " ").replace("-", " ").strip()
    return label.title() if label else alias


def _json_safe(value: Any) -> Any:
    """
    Macht Werte JSON-serialisierbar.

    Jira liefert normalerweise bereits JSON-kompatible Werte.
    Diese Funktion ist bewusst defensiv, falls App-Felder Sondertypen enthalten.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    return str(value)


def _value_to_text(value: Any, indent: int = 0) -> str:
    """
    Wandelt beliebige Jira-Feldwerte generisch in Text um.

    Unterstützt:
    - Strings / HTML / Jira-Markup
    - Zahlen / Boolesche Werte
    - Listen
    - Dictionaries
    - Xray-ähnliche verschachtelte Schrittstrukturen

    Zeilenumbrüche werden bewusst erhalten, damit Gherkin lesbar bleibt.
    """
    prefix = " " * indent

    if value is None:
        return ""

    if isinstance(value, str):
        return TextCleaner.clean_preserve_lines(value)

    if isinstance(value, (int, float, bool)):
        return str(value)

    if isinstance(value, list):
        parts = []

        for item in value:
            item_text = _value_to_text(item, indent + 2)
            if not item_text:
                continue

            item_lines = item_text.splitlines()
            if not item_lines:
                continue

            first_line = item_lines[0]
            remaining_lines = item_lines[1:]

            if remaining_lines:
                parts.append(f"{prefix}- {first_line}")
                parts.extend(f"{prefix}  {line}" for line in remaining_lines)
            else:
                parts.append(f"{prefix}- {first_line}")

        return "\n".join(parts).strip()

    if isinstance(value, dict):
        # Häufige Jira-Objekte kompakt darstellen.
        for simple_key in ("value", "name", "key", "displayName"):
            simple_value = value.get(simple_key)
            if isinstance(simple_value, (str, int, float, bool)) and str(simple_value).strip():
                # Wenn das Objekt nur wenige technische Zusatzfelder enthält, reicht der sprechende Wert.
                meaningful_keys = [key for key, item in value.items() if item not in (None, "", [], {})]
                if len(meaningful_keys) <= 2:
                    return _value_to_text(simple_value, indent)

        parts = []
        for key, item in value.items():
            item_text = _value_to_text(item, indent + 2)
            if not item_text:
                continue

            item_lines = item_text.splitlines()
            if not item_lines:
                continue

            clean_key = TextCleaner.clean_preserve_lines(str(key))
            first_line = item_lines[0]
            remaining_lines = item_lines[1:]

            parts.append(f"{prefix}{clean_key}: {first_line}")
            parts.extend(f"{prefix}  {line}" for line in remaining_lines)

        return "\n".join(parts).strip()

    return TextCleaner.clean_preserve_lines(str(value))


def _extract_configured_custom_fields(
    fields: Dict[str, Any],
    rendered: Dict[str, Any],
    custom_fields: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    """
    Extrahiert alle über JIRA_CUSTOM_FIELDS konfigurierten Felder generisch.

    Wichtig:
    - Leere Custom Fields werden NICHT in den Export übernommen.
    - Dadurch erscheinen z.B. cucumber_scenario, manual_test_steps oder
      generic_test_definition nur dann in metadata/content/raw_content,
      wenn tatsächlich ein Wert vorhanden ist.
    - Die Logik ist absichtlich generisch und gilt für alle konfigurierten Custom Fields.
    """
    extracted: Dict[str, Dict[str, Any]] = {}

    for alias, field_id in custom_fields.items():
        raw_value = fields.get(field_id)
        rendered_value = rendered.get(field_id) if rendered else None

        if rendered_value not in (None, "", [], {}):
            text_value = _value_to_text(rendered_value)
        else:
            text_value = _value_to_text(raw_value)

        # Neu:
        # Custom Field komplett überspringen, wenn der bereinigte Text leer ist.
        if not text_value or not text_value.strip():
            continue

        extracted[alias] = {
            "field_id": field_id,
            "label": _label_from_alias(alias),
            "value": text_value,
            "raw": _json_safe(raw_value),
        }

    return extracted


def build_rag_document(
    issue: Dict[str, Any],
    epic_link_field: str = DEFAULT_EPIC_LINK_FIELD,
    custom_fields: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Transformiert ein Jira-Issue in ein RAG-optimiertes Dokument.
    """
    custom_fields = custom_fields or {}

    fields = issue.get("fields", {})
    # Jira liefert renderedFields auf Issue-Top-Level, wenn expand=renderedFields gesetzt ist.
    # Der alte Zugriff auf fields.renderedFields bleibt als defensiver Fallback erhalten.
    rendered = issue.get("renderedFields") or fields.get("renderedFields", {}) or {}
    key = issue.get("key", "UNKNOWN")

    description_clean = TextCleaner.extract_text_from_rendered(rendered, "description") or TextCleaner.clean(
        fields.get("description")
    )

    summary_clean = TextCleaner.clean(fields.get("summary", ""))

    # Kommentare chronologisch sortieren
    comments_raw = fields.get("comment", {})
    comments_list = comments_raw.get("comments", [])

    comments_text = []
    for c in sorted(comments_list, key=lambda x: x.get("created", "")):
        body = TextCleaner.extract_text_from_rendered(c.get("renderedBody"), "body") or TextCleaner.clean(c.get("body"))
        author = c.get("author", {}).get("displayName", "Unbekannt")
        date = TextCleaner.format_timestamp(c.get("created"))
        if body:
            comments_text.append(f"[{date}] {author}: {body}")

    comments_joined = "\n\n".join(comments_text)

    status_obj = fields.get("status", {})
    status_name = status_obj.get("name", "") if isinstance(status_obj, dict) else str(status_obj)
    status_category = status_obj.get("statusCategory", {}).get("name", "") if isinstance(status_obj, dict) else ""

    resolution_obj = fields.get("resolution", {})
    resolution_name = resolution_obj.get("name", "") if isinstance(resolution_obj, dict) else ""

    labels = fields.get("labels", [])
    priority_obj = fields.get("priority", {})
    priority_name = priority_obj.get("name", "") if isinstance(priority_obj, dict) else ""

    issuetype_obj = fields.get("issuetype", {})
    issuetype_name = issuetype_obj.get("name", "") if isinstance(issuetype_obj, dict) else ""

    configured_custom_fields = _extract_configured_custom_fields(fields, rendered, custom_fields)

    content_parts = [f"# {summary_clean}"]
    if description_clean:
        content_parts.append(description_clean)

    for alias, custom_field in configured_custom_fields.items():
        value = custom_field.get("value", "")
        if value:
            label = custom_field.get("label") or _label_from_alias(alias)
            content_parts.append(f"## {label}\n\n{value}")

    if comments_joined:
        content_parts.append(f"## Kommentare\n\n{comments_joined}")

    content = "\n\n".join(content_parts)

    return {
        "metadata": {
            "key": key,
            "summary": summary_clean,
            "status": status_name,
            "status_category": status_category,
            "resolution": resolution_name,
            "priority": priority_name,
            "issuetype": issuetype_name,
            "created": TextCleaner.format_timestamp(fields.get("created")),
            "labels": labels,
            "epic_link": _extract_epic_link(fields, epic_link_field),
            "issue_links": _extract_issue_links(fields),
            "custom_fields": {
                alias: {
                    "field_id": data["field_id"],
                    "label": data["label"],
                    "value": data["value"],
                }
                for alias, data in configured_custom_fields.items()
            },
        },
        "content": content,
        "raw_content": {
            "description": description_clean,
            "comments": comments_text,
            "custom_fields": configured_custom_fields,
        },
    }


class RAGExporter:
    """Exportiert Jira-Issues als RAG-optimiertes JSON."""

    def __init__(self, client: JiraClient, output_path: str, jql: Optional[str] = None):
        self.client = client
        self.output_path = Path(output_path)
        self.jql = jql  # None -> client verwendet config.jql

    def export(self) -> List[Dict[str, Any]]:
        """Lädt alle Issues und speichert als JSON."""
        documents: List[Dict[str, Any]] = []

        for issue in self.client.fetch_all_issues(self.jql):
            try:
                doc = build_rag_document(
                    issue,
                    self.client.config.epic_link_field,
                    self.client.config.custom_fields,
                )
                documents.append(doc)
                logger.debug(f"Dokument erstellt für {doc['metadata']['key']}")
            except Exception as e:
                key = issue.get("key", "UNKNOWN")
                logger.error(f"Fehler bei Issue {key}: {e}", exc_info=True)

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(documents, f, indent=2, ensure_ascii=False)

        logger.info(f"✓ {len(documents)} Dokumente exportiert → {self.output_path}")
        return documents
