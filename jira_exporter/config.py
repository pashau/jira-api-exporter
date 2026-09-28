"""Konfigurationsmanagement für Jira RAG Export."""

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Tuple

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

EXPORT_DIR = "jira-exports"


def _derive_filename_from_jql(jql: str) -> str:
    """
    Versucht, einen sinnvollen Dateinamen aus der JQL-Abfrage abzuleiten.
    Erkennt Project und IssueType: 'project = "FOO" AND issuetype = "Bug"'
    -> 'jira-exports/jira_foo_bug_tickets.json'
    """
    parts = [f"{EXPORT_DIR}/jira"]

    # 1. Project Name extrahieren
    # Regex ignoriert Whitespace und Zitate
    project_match = re.search(r'project\s*=\s*["\']?([A-Za-z0-9_]+)["\']?', jql, re.IGNORECASE)
    if project_match:
        parts.append(project_match.group(1).strip().lower())

    # 2. IssueType extrahieren
    # Wir suchen nach einfachen Zuweisungen (issuetype = "Value")
    issuetype_match = re.search(r'issuetype\s*=\s*["\']?([A-Za-z0-9_]+)["\']?', jql, re.IGNORECASE)
    if issuetype_match:
        parts.append(issuetype_match.group(1).strip().lower())

    # Fallback, falls nichts erkannt wurde
    if len(parts) == 1:
        parts.append("default")

    # Dateinamen zusammenbauen
    return f"{'_'.join(parts)}_tickets.json"


@dataclass(frozen=True)
class ExportJob:
    """Ein einzelner Export: eine JQL-Abfrage und die zugehörige Ausgabedatei."""

    jql: str
    output_file: str


def _parse_export_entries(raw: str, source: str) -> List[ExportJob]:
    """Parst eine JSON-Liste [{"jql": ..., "output_file": ...}, ...] zu ExportJobs."""
    try:
        entries: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Ungültiges JSON in {source}: {e}") from e

    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{source} muss eine nicht-leere JSON-Liste sein.")

    jobs: List[ExportJob] = []
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: Eintrag #{i} muss ein Objekt mit 'jql' (und optional 'output_file') sein.")

        jql = entry.get("jql")
        if not isinstance(jql, str) or not jql.strip():
            raise ValueError(f"{source}: Eintrag #{i} hat kein gültiges 'jql'.")
        jql = jql.strip()

        output_file = entry.get("output_file")
        if output_file is None or output_file == "":
            output_file = _derive_filename_from_jql(jql)
            logger.info(f"Eintrag #{i}: Kein output_file gesetzt. Abgeleiteter Name: {output_file}")
        elif not isinstance(output_file, str):
            raise ValueError(f"{source}: Eintrag #{i}: 'output_file' muss ein String sein.")
        elif not os.path.dirname(output_file):
            # Reiner Dateiname -> im Standard-Exportverzeichnis ablegen
            output_file = f"{EXPORT_DIR}/{output_file}"

        jobs.append(ExportJob(jql=jql, output_file=output_file))

    return jobs


def _ensure_unique_outputs(jobs: List[ExportJob]) -> None:
    """Verhindert, dass zwei Exports dieselbe Datei überschreiben."""
    seen = {}
    for i, job in enumerate(jobs, 1):
        key = os.path.normcase(os.path.normpath(job.output_file))
        if key in seen:
            raise ValueError(
                f"Eintrag #{seen[key]} und #{i} schreiben beide nach '{job.output_file}'. "
                "Bitte eindeutige 'output_file'-Werte vergeben."
            )
        seen[key] = i


def load_export_jobs() -> List[ExportJob]:
    """
    Lädt die Export-Jobs aus der Umgebung. Reihenfolge der Quellen:

    1. JIRA_EXPORTS_FILE: Pfad zu einer JSON-Datei mit einer Liste von Jobs
    2. JIRA_EXPORTS:      JSON-Liste direkt als Umgebungsvariable
    3. JIRA_JQL / JIRA_OUTPUT_FILE: einzelner Export (bisheriges Verhalten)
    """
    exports_file = os.getenv("JIRA_EXPORTS_FILE")
    exports_inline = os.getenv("JIRA_EXPORTS")

    if exports_file or exports_inline:
        if os.getenv("JIRA_JQL") or os.getenv("JIRA_OUTPUT_FILE"):
            logger.warning("JIRA_JQL/JIRA_OUTPUT_FILE werden ignoriert, da JIRA_EXPORTS(_FILE) gesetzt ist.")

        if exports_file:
            try:
                raw = Path(exports_file).read_text(encoding="utf-8")
            except OSError as e:
                raise ValueError(f"JIRA_EXPORTS_FILE '{exports_file}' konnte nicht gelesen werden: {e}") from e
            jobs = _parse_export_entries(raw, f"JIRA_EXPORTS_FILE ({exports_file})")
        else:
            jobs = _parse_export_entries(exports_inline, "JIRA_EXPORTS")
    else:
        jql = os.getenv("JIRA_JQL", "project IS NOT EMPTY")
        explicit_output = os.getenv("JIRA_OUTPUT_FILE")
        if explicit_output:
            output_file = explicit_output
        else:
            output_file = _derive_filename_from_jql(jql)
            logger.info(f"Kein Output-Filename gesetzt. Abgeleiteter Name: {output_file}")
        jobs = [ExportJob(jql=jql, output_file=output_file)]

    _ensure_unique_outputs(jobs)

    # Sicherstellen, dass die Zielverzeichnisse existieren
    for job in jobs:
        output_dir = os.path.dirname(job.output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

    return jobs


@dataclass
class JiraConfig:
    """Zentralisierte Konfiguration für Jira API Zugriffe."""

    domain: str
    pat_token: str
    jql: str
    max_results: int = 50
    output_file: str = "jira-exports/jira_knowledge_source.json"
    verify_ssl: bool = True
    max_retries: int = 3
    retry_delay: float = 2.0
    timeout: int = 30
    # Alle auszuführenden Exports. `jql`/`output_file` oben entsprechen dem ersten Job
    # (Abwärtskompatibilität).
    jobs: Tuple[ExportJob, ...] = ()

    @classmethod
    def from_env(cls) -> "JiraConfig":
        """Lädt Konfiguration aus Umgebungsvariablen."""
        domain = os.getenv("JIRA_DOMAIN")
        pat_token = os.getenv("JIRA_PAT_TOKEN")

        if not domain or not pat_token:
            raise ValueError("Fehler: JIRA_DOMAIN und JIRA_PAT_TOKEN müssen als Umgebungsvariablen gesetzt sein.")

        jobs = load_export_jobs()

        return cls(
            domain=domain.rstrip("/"),
            pat_token=pat_token,
            jql=jobs[0].jql,
            max_results=int(os.getenv("JIRA_MAX_RESULTS", "50")),
            output_file=jobs[0].output_file,
            verify_ssl=os.getenv("JIRA_VERIFY_SSL", "true").lower() == "true",
            max_retries=int(os.getenv("JIRA_MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("JIRA_RETRY_DELAY", "2.0")),
            timeout=int(os.getenv("JIRA_TIMEOUT", "30")),
            jobs=tuple(jobs),
        )

    @property
    def search_url(self) -> str:
        return f"{self.domain}/rest/api/2/search"