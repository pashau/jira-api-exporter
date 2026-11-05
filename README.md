# Jira RAG Export Tool

[![CI Status](https://github.com/pashau/jira-api-exporter/actions/workflows/lint.yml/badge.svg)](https://github.com/pashau/jira-api-exporter/actions)

Export Jira tickets for RAG pipelines. The tool loads tickets via one or more JQL queries, cleans Jira markup/HTML, enriches metadata, and writes JSON files suitable for vector databases or downstream processing.

## Features

- Export Jira issues via JQL
- Support for single or multiple exports
- Clean `summary`, `description`, and `comments`
- Export issue metadata such as status, priority, labels, epic link, and issue links
- Configurable Jira custom fields via `.env`
- Xray-compatible export of test definitions such as:
  - Cucumber Scenario
  - Manual Test Steps
  - Generic Test Definition
- Empty configured custom fields are skipped automatically
- Docker and local Python execution supported

## Quick Start

### Docker

```bash
docker build -t jira-rag-exporter .
docker run --env-file .env -v $(pwd)/jira-exports:/app/jira-exports jira-rag-exporter
```

If you use `JIRA_EXPORTS_FILE`, mount it as well:

```bash
docker run --env-file .env \
  -e JIRA_EXPORTS_FILE=/app/exports.json \
  -v $(pwd)/exports.json:/app/exports.json \
  -v $(pwd)/jira-exports:/app/jira-exports \
  jira-rag-exporter
```

### Local Python

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
python -m jira_exporter
```

On Windows you can also run:

```bash
py -m jira_exporter
```

The tool logs the number of matching tickets, writes the export files, and returns exit code `1` if any configured export fails.

## Configuration

Create a `.env` file in the project root (copy `.env.example`).

### Single Export

Use `JIRA_JQL` and optionally `JIRA_OUTPUT_FILE`.

```env
JIRA_JQL=project = "PROJ" AND status = Closed
JIRA_OUTPUT_FILE=proj_closed.json
```

If `JIRA_OUTPUT_FILE` is omitted, the tool derives a filename from the JQL and writes it to `jira-exports/`.

## Multiple Exports

Use `JIRA_EXPORTS_FILE` for several JQL queries in one run.

`.env`:

```env
JIRA_EXPORTS_FILE=exports.json
```

`exports.json`:

```json
[
  {
    "jql": "project = \"PROJ\" AND status = Closed",
    "output_file": "proj_closed.json"
  },
  {
    "jql": "project = \"OPS\" AND issuetype = Bug ORDER BY created DESC",
    "output_file": "ops_bugs.json"
  },
  {
    "jql": "project = \"DOCS\""
  }
]
```

Alternatively, provide the same JSON inline:

```env
JIRA_EXPORTS=[{"jql":"project = PROJ","output_file":"proj.json"}]
```

Priority order:

| Priority | Variable | Result |
| --- | --- | --- |
| 1 | `JIRA_EXPORTS_FILE` | JSON file with export jobs |
| 2 | `JIRA_EXPORTS` | Inline JSON export jobs |
| 3 | `JIRA_JQL` + `JIRA_OUTPUT_FILE` | Single export |

If `JIRA_EXPORTS_FILE` or `JIRA_EXPORTS` is set, `JIRA_JQL` and `JIRA_OUTPUT_FILE` are ignored.

## Custom Fields

Additional Jira fields can be exported generically using `JIRA_CUSTOM_FIELDS`.

Recommended format:

```env
JIRA_CUSTOM_FIELDS=cucumber_scenario=cf[10204],manual_test_steps=cf[10206],generic_test_definition=cf[10205]
```

Supported field ID formats:

```text
cf[10204]
customfield_10204
10204
```

### Xray Test Fields

Example for Xray test definitions:

```env
JIRA_CUSTOM_FIELDS=cucumber_scenario=cf[10204],manual_test_steps=cf[10206],generic_test_definition=cf[10205]
```

Meaning:

| Alias | Jira/Xray Field |
| --- | --- |
| `cucumber_scenario` | Cucumber Scenario |
| `manual_test_steps` | Manual Test Steps |
| `generic_test_definition` | Generic Test Definition |

Configured custom fields are exported only when their cleaned value is not empty. Empty values such as `""`, `null`, empty lists, or whitespace-only text are skipped.

This means a ticket with only a Cucumber Scenario will export only `cucumber_scenario`; empty Manual or Generic definitions will not appear in `metadata`, `content`, or `raw_content`.

## `.env` Format Notes

Keep complex values on one line. Do not write multiline JSON in `.env`.

## Output Format

The output is a JSON array. Each ticket contains:

| Section | Description |
| --- | --- |
| `metadata` | Filterable issue data |
| `content` | Clean text for embeddings |
| `raw_content` | Cleaned source fields for inspection/debugging |

Example:

```json
{
  "metadata": {
    "key": "PROJ-123",
    "summary": "Example Xray test",
    "status": "Open",
    "status_category": "To Do",
    "resolution": "",
    "priority": "Medium",
    "issuetype": "Test",
    "created": "2024-01-01 12:00:00",
    "labels": ["xray"],
    "epic_link": "PROJ-100",
    "issue_links": [],
    "custom_fields": {
      "cucumber_scenario": {
        "field_id": "customfield_10204",
        "label": "Cucumber Scenario",
        "value": "Feature: Login\nScenario: Successful login\nGiven ..."
      }
    }
  },
  "content": "# Example Xray test\n\n## Cucumber Scenario\n\nFeature: Login\nScenario: Successful login\nGiven ...",
  "raw_content": {
    "description": "",
    "comments": [],
    "custom_fields": {
      "cucumber_scenario": {
        "field_id": "customfield_10204",
        "label": "Cucumber Scenario",
        "value": "Feature: Login\nScenario: Successful login\nGiven ...",
        "raw": "Feature: Login\nScenario: Successful login\nGiven ..."
      }
    }
  }
}
```

## Epic Link

The epic link field differs between Jira instances. Configure it explicitly if needed:

```env
JIRA_EPIC_LINK_FIELD=customfield_10100
```

The value is exported as:

```json
"epic_link": "PROJ-100"
```

If no epic link exists, the value is an empty string.

## Issue Links

Linked issues are exported under `metadata.issue_links`.

Each link contains:

| Field | Description |
| --- | --- |
| `type` | Jira link type, e.g. `Blocks` |
| `direction` | `outward` or `inward` |
| `relation` | Human-readable relation |
| `key` | Linked issue key |
| `summary` | Linked issue summary |
| `status` | Linked issue status |
| `issuetype` | Linked issue type |

## Security

- Store credentials only in `.env` or environment variables.
- Never commit `.env`.
- `.env` is ignored by Git.
- Logs run at `INFO` level by default and should not expose the token.
- Avoid enabling debug logging in shared environments.
