"""Textbereinigung für RAG-optimierte Embeddings."""

import html
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Jira-Markup- und Wiki-Syntax-Patterns
JIRA_MARKUP_PATTERNS = [
    r"\{noformat\}.*?\{noformat\}",
    r"\{code\}.*?\{code\}",
    r"\{quote\}.*?\{quote\}",
    r"\{panel\}.*?\{panel\}",
    r"\{anchor:[^}]*\}",
    r"\{toc\}",
    r"\{table.*?\}",
    r"!\[[^\]]*\]\([^)]*\)",
    r"!#[^)]*\)",
    r"[^a-zA-Z0-9äöüÄÖÜß]\*\*[^*]+\*\*",
    r"[^a-zA-Z0-9äöüÄÖÜß]\*[^*]+\*",
    r"[^a-zA-Z0-9äöüÄÖÜß]-[^-]+-",
    r"\n{3,}",
]

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
JIRA_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\|([^)]+)\)")
USER_MENTION_PATTERN = re.compile(r"~([a-zA-Z0-9._-]+)")


class TextCleaner:
    """Bereinigt Jira-Text für RAG-Pipelines."""

    @staticmethod
    def clean(text: Optional[str]) -> str:
        """Entfernt Markup, HTML und Jira-spezifische Tags."""
        if not text:
            return ""

        cleaned = str(text)
        cleaned = html.unescape(cleaned)
        cleaned = HTML_TAG_PATTERN.sub(" ", cleaned)

        for pattern in JIRA_MARKUP_PATTERNS:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.DOTALL)

        cleaned = JIRA_LINK_PATTERN.sub(r"\1", cleaned)
        cleaned = USER_MENTION_PATTERN.sub(r"@\1", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

        return cleaned

    @staticmethod
    def extract_text_from_rendered(rendered: dict, field: str) -> str:
        """Extrahiert Text aus Jiras renderedFields."""
        if rendered and field in rendered:
            html_content = rendered[field]
            if html_content:
                return TextCleaner.clean(html_content)
        return ""

    @staticmethod
    def format_timestamp(ts: Optional[str]) -> str:
        """Formatiert ISO-Timestamp für menschliche Lesbarkeit."""
        if not ts:
            return "Unbekannt"
        return ts.replace("T", " ").split(".")[0].split("+")[0]
