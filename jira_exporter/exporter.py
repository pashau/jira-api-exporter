"""Export-Logik: Issues → RAG-optimiertes JSON."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cleaner import TextCleaner
from .client import JiraClient

logger = logging.getLogger(__name__)


def build_rag_document(issue: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transformiert ein Jira-Issue in ein RAG-optimiertes Dokument.
    """
    fields = issue.get("fields", {})
    rendered = fields.get("renderedFields", {})
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

    content_parts = [f"# {summary_clean}"]
    if description_clean:
        content_parts.append(description_clean)
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
        },
        "content": content,
        "raw_content": {
            "description": description_clean,
            "comments": comments_text,
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
                doc = build_rag_document(issue)
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
