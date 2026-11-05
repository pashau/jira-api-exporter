"""Konfigurationsmanagement für Jira RAG Export."""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


def _normalize_custom_field_id(raw: str) -> str:
    """
    Normalisiert Jira Custom Field IDs.

    Akzeptiert:
    - customfield_10204
    - cf[10204]
    - 10204

    Gibt für Custom Fields immer customfield_<id> zurück.
    Andere Feldnamen werden unverändert zurückgegeben, damit die Funktion generisch bleibt.
    """
    value = str(raw).strip()

    if not value:
        raise ValueError("Leere Custom-Field-ID ist nicht erlaubt.")

    cf_match = re.fullmatch(r"cf\[(\d+)\]", value, re.IGNORECASE)
    if cf_match:
        return f"customfield_{cf_match.group(1)}"

    numeric_match = re.fullmatch(r"\d+", value)
    if numeric_match:
        return f"customfield_{value}"

    customfield_match = re.fullmatch(r"customfield_(\d+)", value, re.IGNORECASE)
    if customfield_match:
        return f"customfield_{customfield_match.group(1)}"

    # Bewusst generisch: auch Standard-Jira-Felder oder App-Felder zulassen.
    return value


def _parse_custom_fields(raw: str) -> Dict[str, str]:
    """
    Parst JIRA_CUSTOM_FIELDS aus der Umgebung.

    Unterstützte Formate:

    1. JSON-Objekt:
       {"cucumber_scenario": "cf[10204]", "manual_test_steps": "customfield_10206"}

    2. Komma-/Semikolon-getrennte Kurzform:
       cucumber_scenario=cf[10204],manual_test_steps=cf[10206]
    """
    if not raw or not raw.strip():
        return {}

    raw = raw.strip()

    # Zuerst JSON versuchen.
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None

    if parsed is not None:
        if not isinstance(parsed, dict):
            raise ValueError('JIRA_CUSTOM_FIELDS muss ein JSON-Objekt sein, z.B. {"name": "cf[12345]"}.')

        custom_fields: Dict[str, str] = {}
        for alias, field_id in parsed.items():
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("JIRA_CUSTOM_FIELDS enthält einen ungültigen Alias.")
            if not isinstance(field_id, str) or not field_id.strip():
                raise ValueError(f"JIRA_CUSTOM_FIELDS: Feld-ID für Alias '{alias}' ist ungültig.")

            custom_fields[alias.strip()] = _normalize_custom_field_id(field_id)

        return custom_fields

    # Fallback: key=value,key=value oder key:value;key:value
    entries = re.split(r"\s*[,;]\s*", raw)
    custom_fields = {}

    for entry in entries:
        if not entry:
            continue

        if "=" in entry:
            alias, field_id = entry.split("=", 1)
        elif ":" in entry:
            alias, field_id = entry.split(":", 1)
        else:
            raise ValueError(
                f"JIRA_CUSTOM_FIELDS Kurzform muss Einträge als alias=field_id enthalten, ungültiger Eintrag: '{entry}'"
            )

        alias = alias.strip()
        field_id = field_id.strip()

        if not alias:
            raise ValueError(f"JIRA_CUSTOM_FIELDS enthält einen Eintrag ohne Alias: '{entry}'")
        if not field_id:
            raise ValueError(f"JIRA_CUSTOM_FIELDS enthält einen Eintrag ohne Feld-ID: '{entry}'")

        custom_fields[alias] = _normalize_custom_field_id(field_id)

    return custom_fields


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
    # Custom-Field-ID des "Epic Link" (instanzabhängig, Standard: customfield_10100)
    epic_link_field: str = "customfield_10100"
    # Generische zusätzliche Custom Fields, z.B. Xray Cucumber Scenario / Manual Steps / Generic Test Definition.
    custom_fields: Dict[str, str] = field(default_factory=dict)
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
        custom_fields = _parse_custom_fields(os.getenv("JIRA_CUSTOM_FIELDS", ""))

        if custom_fields:
            logger.info(
                "Zusätzliche Custom Fields konfiguriert: "
                + ", ".join(f"{alias}={field_id}" for alias, field_id in custom_fields.items())
            )

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
            epic_link_field=_normalize_custom_field_id(os.getenv("JIRA_EPIC_LINK_FIELD", "customfield_10100")),
            custom_fields=custom_fields,
            jobs=tuple(jobs),
        )

    @property
    def search_url(self) -> str:
        return f"{self.domain}/rest/api/2/search"
