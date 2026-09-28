"""Haupteinstiegspunkt für den Jira-RAG-Export."""

import logging
import sys

from .client import JiraClient
from .config import JiraConfig
from .exporter import RAGExporter

# Logging konfigurieren: Wichtig: Nicht DEBUG, sonst könnten Token mitgeloggt werden!
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("jira_export")


def main():
    try:
        config = JiraConfig.from_env()
    except Exception as e:
        logger.error(f"❌ Konfiguration ungültig: {str(e)}")
        sys.exit(1)

    logger.info(f"Starte Export für Jira Instanz: {config.domain} ({len(config.jobs)} Export(e))")
    client = JiraClient(config)

    total = len(config.jobs)
    succeeded = 0
    failed = []

    for n, job in enumerate(config.jobs, 1):
        logger.info(f"▶ Export {n}/{total}: {job.jql} → {job.output_file}")
        try:
            documents = RAGExporter(client, job.output_file, job.jql).export()
            logger.info(f"✅ Export {n}/{total}: {len(documents)} Tickets exportiert.")
            succeeded += 1
        except Exception as e:
            # Ein fehlgeschlagener Export soll die übrigen nicht verhindern.
            logger.error(f"❌ Export {n}/{total} fehlgeschlagen ({job.output_file}): {str(e)}")
            failed.append(job)

    logger.info(f"Fertig: {succeeded} von {total} Exports erfolgreich.")
    if failed:
        for job in failed:
            logger.error(f"Fehlgeschlagen: {job.output_file} ← {job.jql}")
        sys.exit(1)


if __name__ == "__main__":
    main()
