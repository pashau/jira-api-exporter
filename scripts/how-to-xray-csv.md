# Xray CSV Import How-To

Convert Jira JSON export to Xray Manual Test CSV.

## Bash

```bash
python xray_csv_from_export.py \
  --input jira-exports/xray_tests.json \
  --output xray_manual_import.csv \
  --summary-prefix "[MY-PREFIX] "
```

## PowerShell

```powershell
py .\xray_csv_from_export.py `
  --input .\jira-exports\xray_tests.json `
  --output .\xray_manual_import.csv `
  --summary-prefix "[MY-PREFIX] "
```

## Options

| Option | Description |
|---|---|
| `--input` | Jira JSON export |
| `--output` | Target CSV file |
| `--summary-prefix` | Optional prefix for test summaries |
| `--include-empty-tests` | Export tests without detected steps |

## Xray CSV Mapping

Map these CSV columns in the Xray Bulk CSV Importer:

| CSV Column | Xray Field |
|---|---|
| `Summary` | `Summary` |
| `Description` | `Description` |
| `Test Type` | `Test Type` |
| `Manual Test Step Action` | `Manual Test Step Action` |
| `Manual Test Step Data` | `Manual Test Step Data` |
| `Manual Test Step Expected Result` | `Manual Test Step Expected Result` |
| `Labels` | `Labels` |

Optional traceability columns:

| CSV Column | Handling |
|---|---|
| `Source Issue Key` | Ignore or map to custom field |
| `Source Step Field` | Ignore or map to custom field |

## Notes

- Only JSON issues with `metadata.issuetype = Test` are exported.
- Output tests are always `Manual`.
- `cucumber_scenario` and `generic_test_definition` are converted to manual steps.
- One CSV row is written per manual step.