# Job Market Tracker

A Python ETL pipeline that collects tech job postings in Israel,
preserves collection history in SQLite, and visualizes which
technologies appear in job descriptions.

The goal is to explore job requirements across Data, BI, AI,
Software and DevOps roles using a repeatable data pipeline.

**Python · Pandas · SQLite · Matplotlib · REST APIs · GitHub Actions**

## Latest results

![Technology mentions](reports/technology_mentions.png)

[Technology report](reports/technology_mentions.csv) ·
[Job classifications](reports/job_classifications.csv) ·
[Collection coverage](reports/collection_coverage.csv)

## How it works

| Stage | What it does | Files |
| --- | --- | --- |
| Extract | Collects postings and saves the original API records | `extract.py`, `extract_search.py`, `raw_storage.py` |
| Transform | Cleans fields, checks locations and classifies job titles | `transform.py`, `job_rules.py` |
| Load | Validates records and preserves collection history in SQLite | `load.py`, `database.py`, `schema.sql` |
| Report | Identifies technology mentions and generates reports | `skill_analysis.py`, `opportunity_rules.py`, `visualize.py` |

`main.py` coordinates the pipeline.
Company boards and search queries are configured in `config.py`.

## Data sources

- **Greenhouse — default:** collects public postings from Similarweb,
  Forter and Gong without an API key.
- **JSearch — optional:** searches across employers for Data Student,
  Software Student and DevOps Student roles in Israel.

Greenhouse reports include matched roles across all seniority levels.
JSearch reports focus on postings with student or entry-level signals.

To configure JSearch, follow the [setup guide](docs/jsearch_setup.md).

## Run locally

Use Python 3.12. From the project folder, run in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:JOB_SOURCE = "greenhouse"
.\.venv\Scripts\python.exe main.py
```

This collects fresh postings, updates the database and generates
the reports in the `reports` folder.

To regenerate reports from stored data without collecting new postings:

```powershell
$env:JOB_SOURCE = "greenhouse"
.\.venv\Scripts\python.exe visualize.py
```

## Storage and history

The database is stored at `data/job_market.sqlite3`.

- `collection_runs` records each collection and its timestamp.
- `job_snapshots` stores the postings observed in each collection.

New collections preserve earlier observations. Reports analyze the
latest stored collection for each selected board or search scope.

Full job descriptions are retained for analysis.
JSearch removes repeated job IDs returned by multiple queries.

## Tests

Run the offline checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use synthetic postings, mocked API responses and temporary
databases. They cover history, duplicate handling, classification,
empty results and pipeline failures.

## Automation

GitHub Actions schedules the pipeline daily at 06:17 UTC.

The workflow runs the tests before collection, saves raw snapshots
as artifacts and commits the updated database and reports after success.

The repository variable `JOB_SOURCE` selects the source.
JSearch credentials are stored as GitHub secrets.

## Limitations and next steps

- Coverage is limited to the configured company boards or one page
  per JSearch query.
- Role and experience labels use rules and require human review.
- Technology mentions do not necessarily indicate mandatory requirements.
- Each technology is counted once per posting; percentages can overlap.
- Historical trend charts and manual evaluation of classification
  accuracy are planned improvements.