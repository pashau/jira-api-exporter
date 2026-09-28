"""REST API Client für Jira Data Center mit Paginierung und Retry-Logik."""

import logging
import time
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.exceptions import ConnectionError, SSLError, Timeout

from .config import JiraConfig

logger = logging.getLogger(__name__)

# Felder, die für RAG relevant sind
RAG_FIELDS = [
    "key",
    "summary",
    "description",
    "comment",
    "status",
    "created",
    "resolution",
    "issuetype",
    "priority",
    "labels",
]


class JiraClient:
    """REST API Client für Jira Data Center mit Bearer-Token-Auth."""

    def __init__(self, config: JiraConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.pat_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _request_with_retry(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """HTTP-GET mit Retry-Logik für Timeouts und SSL-Fehler."""
        last_error = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.config.timeout,
                    verify=self.config.verify_ssl,
                )
                response.raise_for_status()
                return response.json()

            except (Timeout, ConnectionError, SSLError) as e:
                last_error = e
                wait_time = self.config.retry_delay * attempt
                logger.warning(f"Versuch {attempt}/{self.config.max_retries} gescheitert: {e}. Warte {wait_time}s...")
                time.sleep(wait_time)

            except requests.HTTPError as e:
                logger.error(f"HTTP-Fehler: {e.response.status_code} - {e}")
                raise

        raise last_error or RuntimeError("Unbekannter Fehler")

    def fetch_all_issues(self, jql: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
        """
        Hole alle Issues via paginierte JQL-Suche.
        Yields jedes Issue einzeln für speichereffiziente Verarbeitung.

        Ohne Angabe von `jql` wird `config.jql` verwendet.
        """
        jql = jql or self.config.jql
        start_at = 0
        total_issues = 0
        first_request = True

        while True:
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": self.config.max_results,
                "fields": ",".join(RAG_FIELDS),
            }

            logger.info(f"Abfrage: startAt={start_at}, maxResults={self.config.max_results}")

            data = self._request_with_retry(self.config.search_url, params)

            # Log actual total count from Jira
            current_total = data.get("total", 0)
            if first_request:
                logger.info(f"🔍 JQL-Filter ergibt insgesamt {current_total} Treffer.")
                total_issues = current_total
                first_request = False
            elif current_total != total_issues:
                logger.warning(f"Treffer-Anzahl hat sich geändert: {total_issues} -> {current_total}")
                total_issues = current_total

            issues: List[Dict[str, Any]] = data.get("issues", [])
            if not issues:
                logger.info("Keine weiteren Issues gefunden.")
                break

            yield from issues

            if start_at + len(issues) >= total_issues:
                logger.info(f"Alle {total_issues} Issues vom Server abgerufen.")
                break

            start_at += len(issues)
            logger.debug(f"Fortschritt: {min(start_at, total_issues)}/{total_issues}")
