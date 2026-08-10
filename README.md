# Jira RAG Export Tool

[![CI Status](https://github.com/pashau/jira-api-exporter/actions/workflows/lint.yml/badge.svg)](https://github.com/pashau/jira-api-exporter/actions)

Exportiere Jira-Tickets für RAG-Pipelines (Retrieval-Augmented Generation). Das Skript lädt Tickets via JQL, bereinigt den Text von Markup und speichert das Ergebnis als sauberes JSON für Vektordatenbanken.

## 🐳 Docker (Empfohlen)

Der einfachste Weg, das Tool auszuführen, ist Docker. Stelle sicher, dass deine `.env`-Datei vorhanden ist:

```bash
# 1. Image bauen (einmalig)
docker build -t jira-rag-exporter .

# 2. Container starten (lädt .env automatisch)
docker run --env-file .env jira-rag-exporter
```

*Hinweis: Das Ergebnis (`jira_knowledge_source.json`) wird standardmäßig im Container erstellt. Um es dauerhaft zu speichern, mounte einen Volume-Ordner:*
`docker run --env-file .env -v $(pwd)/output:/app/output jira-rag-exporter`

## 💻 Lokale Installation

Falls du keine Container-Umgebung nutzen möchtest, kannst du das Tool direkt über Python ausführen:

### 1. Setup
Erstelle eine virtuelle Umgebung und installiere die Dependencies:

```bash
# Virtuelle Umgebung erstellen
python -m venv .venv # OR with Windows-Launcher: `py -m venv .venv`

# Aktivieren (Windows PowerShell)
.\.venv\Scripts\activate
# Aktivieren (macOS/Linux)
source .venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

### 2. Konfiguration
Erstelle eine `.env`-Datei im Projektstamm mit deinen Zugangsdaten:

```env
JIRA_DOMAIN=https://deine-firma.atlassian.net
JIRA_PAT_TOKEN=DEIN_TOKEN_HIER
JIRA_JQL=project = "PROJ" AND status = Closed
```
*Hinweis:* Falls du kein `JIRA_OUTPUT_FILE` setzt, wird der Name automatisch aus der JQL abgeleitet.

### 3. Ausführen
Starte den Export einfach per Modul-Aufruf:

```bash
python -m jira_exporter
# py -m jira_exporter (Windows)
```

Das Skript gibt die **Trefferanzahl** vor dem Download aus und speichert das Ergebnis im JSON-Format.

## 📄 Output Format
Das JSON enthält für jedes Ticket drei zentrale Bereiche:

1. **`metadata`**: Filterbare Daten wie `key`, `status`, `priority`, `created`.
2. **`content`**: Der bereinigte Text für Embeddings (Zusammenfassung + Beschreibung + Kommentare).
3. **`raw_content`**: Der unveränderte, aber saubere Text der Beschreibung und Kommentare.

Beispiel:
```json
{
  "metadata": { "key": "PROJ-123", "status": "Closed", "created": "2024-01-01 12:00:00" },
  "content": "# Ticket-Zusammenfassung\n\nBereinigte Beschreibung...\n\n## Kommentare\n[2024-01-02] Max: Kommentar-Text",
  "raw_content": { "description": "Bereinigte Beschreibung...", "comments": [...] }
}
```

## 🔒 Sicherheit
- Das Token wird **nur** über Umgebungsvariablen (`.env`) geladen.
- Die `.env`-Datei ist in der `.gitignore` und darf **niemals** in die Versionskontrolle.
- Logs enthalten keine Secrets (Standard `INFO`-Level).




