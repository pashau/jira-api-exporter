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
        logger.info(f"Starte Export für Jira Instanz: {config.domain}")

        client = JiraClient(config)
        exporter = RAGExporter(client, config.output_file)
        documents = exporter.export()

        logger.info(f"✅ Erfolg! {len(documents)} Tickets exportiert.")

    except Exception as e:
        logger.error(f"❌ Export fehlgeschlagen: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
