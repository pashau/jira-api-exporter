"""Konfigurationsmanagement für Jira RAG Export."""

import logging
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _derive_filename_from_jql(jql: str) -> str:
    """
    Versucht, einen sinnvollen Dateinamen aus der JQL-Abfrage abzuleiten.
    Erkennt z.B. 'project = "FOO"' -> 'foo_tickets.json'
    """
    match = re.search(r'project\s*=\s*["\']?([A-Z0-9_]+)["\']?', jql, re.IGNORECASE)
    if match:
        return f"{match.group(1).strip().lower()}_tickets.json"

    return "jira_export_default.json"


@dataclass
class JiraConfig:
    """Zentralisierte Konfiguration für Jira API Zugriffe."""

    domain: str
    pat_token: str
    jql: str
    max_results: int = 50
    output_file: str = "jira_knowledge_source.json"
    verify_ssl: bool = True
    max_retries: int = 3
    retry_delay: float = 2.0
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "JiraConfig":
        """Lädt Konfiguration aus Umgebungsvariablen."""
        domain = os.getenv("JIRA_DOMAIN")
        pat_token = os.getenv("JIRA_PAT_TOKEN")

        if not domain or not pat_token:
            raise ValueError("Fehler: JIRA_DOMAIN und JIRA_PAT_TOKEN müssen als Umgebungsvariablen gesetzt sein.")

        jql = os.getenv("JIRA_JQL", "project IS NOT EMPTY")

        explicit_output = os.getenv("JIRA_OUTPUT_FILE")
        if explicit_output:
            output_file = explicit_output
        else:
            output_file = _derive_filename_from_jql(jql)
            logger.info(f"Kein Output-Filename gesetzt. Abgeleiteter Name: {output_file}")

        return cls(
            domain=domain.rstrip("/"),
            pat_token=pat_token,
            jql=jql,
            max_results=int(os.getenv("JIRA_MAX_RESULTS", "50")),
            output_file=output_file,
            verify_ssl=os.getenv("JIRA_VERIFY_SSL", "true").lower() == "true",
            max_retries=int(os.getenv("JIRA_MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("JIRA_RETRY_DELAY", "2.0")),
            timeout=int(os.getenv("JIRA_TIMEOUT", "30")),
        )

    @property
    def search_url(self) -> str:
        return f"{self.domain}/rest/api/2/search"
