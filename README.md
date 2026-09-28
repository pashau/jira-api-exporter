# Jira RAG Export Tool

[![CI Status](https://github.com/pashau/jira-api-exporter/actions/workflows/lint.yml/badge.svg)](https://github.com/pashau/jira-api-exporter/actions)

Export Jira tickets for RAG pipelines (Retrieval-Augmented Generation). The script loads tickets via one or more JQL queries, cleans the text from markup, and saves each result as clean JSON for vector databases.

## 🐳 Docker (Recommended)

The easiest way to run the tool is with Docker. Make sure your `.env` file exists:

```bash
# 1. Build the image (one-time setup)
docker build -t jira-rag-exporter .

# 2. Start the container (loads .env automatically)
docker run --env-file .env jira-rag-exporter
```

*Note: The result is saved inside the `jira-exports/` folder by default. To persist it, mount an output directory:*

```bash
docker run --env-file .env -v $(pwd)/jira-exports:/app/jira-exports jira-rag-exporter
```

*Multiple exports:* if you use `JIRA_EXPORTS_FILE` (see [Multiple Exports](#multiple-exports)), also mount the file into the container:

```bash
docker run --env-file .env \
  -e JIRA_EXPORTS_FILE=/app/exports.json \
  -v $(pwd)/exports.json:/app/exports.json \
  -v $(pwd)/jira-exports:/app/jira-exports \
  jira-rag-exporter
```

## 💻 Local Installation

If you do not want to use a container environment, you can run the tool directly with Python:

### 1. Setup

Create a virtual environment and install the dependencies:

```bash
# Create virtual environment
python -m venv .venv # OR with Windows launcher: `py -m venv .venv`

# Activate (Windows PowerShell)
.\.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file in the project root with your credentials:

```env
JIRA_DOMAIN=https://your-company.atlassian.net
JIRA_PAT_TOKEN=YOUR_TOKEN_HERE
JIRA_JQL=project = "PROJ" AND status = Closed
```

*Note:* If you do not set `JIRA_OUTPUT_FILE`, the filename is derived automatically from the JQL query and saved in the `jira-exports/` directory (e.g. `jira-exports/jira_myproj_story_tickets.json`).

### Multiple Exports

To export several JQL queries into separate files in a single run, provide a list of `jql` / `output_file` pairs. The easiest way is a JSON file (copy `exports.example.json` to `exports.json`):

```json
[
  { "jql": "project = \"PROJ\" AND status = Closed", "output_file": "proj_closed.json" },
  { "jql": "project = \"OPS\" AND issuetype = Bug ORDER BY created DESC", "output_file": "ops_bugs.json" },
  { "jql": "project = \"DOCS\"" }
]
```

Then reference it in your `.env`:

```env
JIRA_EXPORTS_FILE=exports.json
```

Alternatively, pass the same JSON list inline via `JIRA_EXPORTS='[{"jql": "project = PROJ", "output_file": "proj.json"}]'`.

Which variable wins (highest priority first):

| Priority | Variable | Result |
| -------- | -------- | ------ |
| 1 | `JIRA_EXPORTS_FILE` | Path to a JSON file with a list of exports |
| 2 | `JIRA_EXPORTS` | The same JSON list, inline |
| 3 | `JIRA_JQL` (+ optional `JIRA_OUTPUT_FILE`) | A single export (previous behavior) |

If `JIRA_EXPORTS_FILE` or `JIRA_EXPORTS` is set, `JIRA_JQL` and `JIRA_OUTPUT_FILE` are ignored (a warning is logged).

Rules and behavior:

- **`jql`** is required for every entry.
- **`output_file`** is optional. If omitted, the filename is derived from the JQL (see the note above).
- A bare filename such as `proj_closed.json` is saved in `jira-exports/`. Paths that include a directory are used as given.
- Every entry must resolve to a **unique** output file. Duplicates abort the run at startup instead of silently overwriting each other.
- Exports run sequentially and independently: if one fails, the remaining exports still run. A summary is logged at the end and the exit code is `1` if any export failed. A failed export does not overwrite its previous output file.

### 3. Run

Start the export using the module command:

```bash
python -m jira_exporter
# py -m jira_exporter (Windows)
```

For each export, the script prints the **number of matching tickets** before downloading and saves the JSON result in `jira-exports/` (or the configured output path).

## 📄 Output Format

The JSON contains three main sections for each ticket:

1. **`metadata`**: Filterable data such as `key`, `status`, `priority`, and `created`.
2. **`content`**: The cleaned text for embeddings (summary + description + comments).
3. **`raw_content`**: The unchanged but cleaned text of the description and comments.

Example:

```json
{
  "metadata": { "key": "PROJ-123", "status": "Closed", "created": "2024-01-01 12:00:00" },
  "content": "# Ticket Summary\n\nCleaned description...\n\n## Comments\n[2024-01-02] Max: Comment text",
  "raw_content": { "description": "Cleaned description...", "comments": [...] }
}
```

## 🔒 Security

- The token is loaded **only** via environment variables (`.env`).
- The `.env` file is included in `.gitignore` and must **never** be committed to version control.
- Logs do not contain secrets by default (`INFO` level).