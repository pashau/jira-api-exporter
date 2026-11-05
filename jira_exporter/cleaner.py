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
    r"\n{3,}",
]

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# Inline-Hervorhebungen (*bold*, **bold**): nur das Markup entfernen, den
# eingeschlossenen Text behalten. Begrenzt auf eine Zeile (kein \n im Inhalt),
# damit nicht versehentlich der Text zwischen zwei unzusammenhängenden
# *Label:*-Zeilen verschluckt wird. (?<!\w)/(?!\w) verhindert Treffer mitten in
# Wörtern/Zahlen (z. B. "60°-120°").
BOLD_PATTERN = re.compile(r"(?<!\w)\*\*([^\n*]+?)\*\*(?!\w)")
ITALIC_PATTERN = re.compile(r"(?<!\w)\*([^\n*]+?)\*(?!\w)")
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

        # Erst ** (bold), dann * (italic) - sonst würde die Italic-Regex die
        # beiden Sterne eines Bold-Paares als zwei Italic-Treffer missverstehen.
        cleaned = BOLD_PATTERN.sub(r"\1", cleaned)
        cleaned = ITALIC_PATTERN.sub(r"\1", cleaned)

        cleaned = JIRA_LINK_PATTERN.sub(r"\1", cleaned)
        cleaned = USER_MENTION_PATTERN.sub(r"@\1", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

        return cleaned

    @staticmethod
    def clean_preserve_lines(text: Optional[str]) -> str:
        """
        Entfernt Markup und HTML, erhält aber Zeilenumbrüche.

        Das ist besonders wichtig für strukturierte Inhalte wie:
        - Gherkin/Cucumber Scenarios
        - Manual Test Steps
        - Generic Test Definitions
        """
        if not text:
            return ""

        cleaned = str(text)
        cleaned = html.unescape(cleaned)

        # HTML-Blocktrenner in Zeilenumbrüche übersetzen, bevor generische Tags entfernt werden.
        cleaned = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", cleaned)
        cleaned = re.sub(r"(?i)</\s*p\s*>", "\n", cleaned)
        cleaned = re.sub(r"(?i)</\s*div\s*>", "\n", cleaned)
        cleaned = re.sub(r"(?i)</\s*li\s*>", "\n", cleaned)
        cleaned = HTML_TAG_PATTERN.sub(" ", cleaned)

        for pattern in JIRA_MARKUP_PATTERNS:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.DOTALL)

        cleaned = BOLD_PATTERN.sub(r"\1", cleaned)
        cleaned = ITALIC_PATTERN.sub(r"\1", cleaned)
        cleaned = JIRA_LINK_PATTERN.sub(r"\1", cleaned)
        cleaned = USER_MENTION_PATTERN.sub(r"@\1", cleaned)

        # Horizontale Whitespaces normalisieren, Zeilenumbrüche erhalten.
        cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
        lines = [line.strip() for line in cleaned.splitlines()]
        cleaned = "\n".join(lines)

        # Mehr als zwei Leerzeilen reduzieren.
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

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
    def extract_text_from_rendered_preserve_lines(rendered: dict, field: str) -> str:
        """Extrahiert Text aus Jiras renderedFields und erhält Zeilenumbrüche."""
        if rendered and field in rendered:
            html_content = rendered[field]
            if html_content:
                return TextCleaner.clean_preserve_lines(html_content)
        return ""

    @staticmethod
    def format_timestamp(ts: Optional[str]) -> str:
        """Formatiert ISO-Timestamp für menschliche Lesbarkeit."""
        if not ts:
            return "Unbekannt"
        return ts.replace("T", " ").split(".")[0].split("+")[0]
