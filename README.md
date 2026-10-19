# Job Market Tracker

A Python ETL pipeline that collects public job postings, preserves
collection history in SQLite, and visualizes technology mentions
in Israel-based Data, BI, AI, software, and DevOps-related roles.

## Project goal

Build a reproducible workflow for exploring job requirements and
changes across collection dates.

Two collection modes are available:

- `JOB_SOURCE=greenhouse` monitors Similarweb, Forter and Gong without an API key.
- `JOB_SOURCE=jsearch` searches across employers using Data Student,
  Software Student, and DevOps Student queries in Israel.

Greenhouse remains the default until JSearch credentials are configured.
[Follow the JSearch setup guide](docs/jsearch_setup.md) to switch the daily
workflow. The code supports both the direct OpenWeb Ninja and RapidAPI gateways.
Student/entry-level labels are explainable candidates for human review.

## Current implementation

- Fetch public postings from Greenhouse or query-based results from JSearch.
- Preserve full descriptions and deduplicate repeated JSearch job IDs across queries.
- Save raw job records with UTC collection metadata as JSON snapshots.
- Normalize nested fields and clean text columns using Pandas.
- Check JSearch country codes and use location-text rules when a code is missing.
- Assign Data/BI/AI, software and DevOps families, title seniority hints,
  and student/entry-level candidate labels with evidence and rule version.
- Validate records and store collection history in SQLite.
- Extract technology mentions from job descriptions.
- Generate technology-mention, collection-coverage and per-job classification CSVs,
  plus a Matplotlib chart.
- Run the complete pipeline through `main.py` with progress and error logging.

## Latest report

![Technology mentions](reports/technology_mentions.png)

[View the CSV report](reports/technology_mentions.csv)

In Greenhouse mode, the chart analyzes title-matched postings of all
seniorities from the latest collection of each board. In JSearch mode,
it analyzes student/entry-level candidates from the latest complete
query batch. The provider and scope are recorded in the technology CSV;
historical observations are not added to current posting counts.

Each successful run also writes `reports/job_classifications.csv`, with
all Israel postings from the selected source, including role, seniority,
candidate status, explicit experience evidence, reason, skills, and job URL.
This includes experienced and uncertain postings so exclusions remain auditable.

[View collection coverage](reports/collection_coverage.csv) for each
board's collection ID, timestamp, raw and Israel posting counts,
matched posting count, and empty matched-description count. Boards
with zero matches remain in this report. Missing board collections
raise an error instead of silently reducing the reporting scope.

In the technology CSV, `board_tokens` and `collection_ids` share the
same order. Snapshot time bounds show the range of collection times.
The coverage CSV retains these details even when the technology CSV
has no data rows. For JSearch, `board_token` is the versioned query-set
identifier, and the coverage row describes the whole batch, not one company.
The `company` column is a display label for that batch. Candidate and analyzed
counts show the difference between returned jobs and the chart's selected scope.

Each technology is counted once per posting. Percentages use all
analyzed postings as the denominator. A posting can mention multiple
technologies, so percentages do not need to sum to 100%.

## Data source

- Provider: Greenhouse Job Board API
- Boards: Similarweb (`similarweb`), Forter (`forter`), Gong (`gongio`)
- Configuration: `GREENHOUSE_BOARDS` in `config.py`
- Authentication: No API key required for the public GET endpoint
- Documentation: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)

Greenhouse requests full descriptions using `content=true`.

JSearch uses `country=il`, an Israel location in each query, and one page
per query. The three-query batch uses three requests per complete run.
It is a limited search sample, not an exhaustive market crawl. There are
no automatic retries, extra pages, or automatic subscription changes.
The raw snapshot records query counts and provider provenance without secrets.
See the [provider documentation](https://www.openwebninja.com/api/jsearch/docs).

## Local setup

Tested with Python 3.12.10 on Windows.

From the project directory, run these commands in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

A successful run saves one raw snapshot per board, loads the processed
records into SQLite, and updates the technology CSV, chart, coverage CSV,
and classification CSV. JSearch stores one combined query batch per run.

To regenerate reports from the latest stored collection per board without
fetching new data:

```powershell
.\.venv\Scripts\python.exe visualize.py
```

If Windows prevents overwriting a report, close the application
displaying that file and rerun `visualize.py`.

## Project structure

| File | Responsibility |
| --- | --- |
| `config.py` | Configure board identifiers and company display names |
| `extract.py` | Fetch postings from Greenhouse |
| `extract_search.py` | Fetch a bounded set of JSearch queries |
| `search_pipeline.py` | Collect, normalize, and report a complete JSearch batch |
| `opportunity_rules.py` | Explain student/entry-level candidates and uncertain cases |
| `raw_storage.py` | Save raw records and collection metadata |
| `transform.py` | Normalize records and apply location rules |
| `job_rules.py` | Classify job titles and seniority hints |
| `schema.sql` | Define tables, keys, and constraints |
| `database.py` | Initialize the database and inspect row counts |
| `load.py` | Validate and load a collection transactionally |
| `skill_analysis.py` | Select the latest collection per board using SQL and extract technology mentions |
| `visualize.py` | Export technology mentions, chart, and collection coverage |
| `main.py` | Coordinate the complete pipeline |
| `requirements.txt` | Record Python dependencies |
| `tests/test_multi_company.py` | Check collection selection, reporting, and pipeline failure behavior offline |
| `tests/test_jsearch.py` | Check API contracts, duplicate removal, country evidence, classifications and failures |

## Data storage and collection history

The database is stored at `data/job_market.sqlite3`.

- `collection_runs`: Collection metadata, timestamps, and posting counts.
- `job_snapshots`: Postings associated with each collection, including
  descriptions and classification results.

All postings passing the Israel location rules are stored, including
`matched`, `needs_review`, and `not_matched` role statuses.
Technology reports use only `matched` postings; JSearch further restricts
the chart to explicit student, junior or entry-level candidates. The full
classification CSV keeps every Israel posting from the latest selected scopes.
Candidate labels are derived from stored descriptions at report time and
include a rule version; the database retains the original full descriptions.

A collection is identified by its source, board token, and UTC
snapshot timestamp. Loading the same snapshot again refreshes that
collection without adding another copy.

A new extraction creates a new collection. The same posting can
therefore appear across multiple dates as part of its history.

Each Greenhouse execution collects every configured board. Board loads
use separate transactions: a later failure leaves earlier successful
collections available for inspection. Reports are generated after all
boards complete. Standalone report generation reads the latest stored
collection per board; the coverage CSV makes their timestamps explicit.

A JSearch execution requires every query to succeed before storing its batch.
A failed query raises an error instead of saving partial search results as
success. Historical Greenhouse records stay in the same database, identified
by their source. Reports select one provider and do not mix the two coverages.

For this small portfolio version, the SQLite database and latest
reports are included in version control. Raw JSON snapshots,
virtual environments, and temporary files are excluded by `.gitignore`.

## Initial verified local run

An end-to-end Similarweb run on 2026-10-14 produced:

| Metric | Count |
| --- | ---: |
| Postings received | 68 |
| Postings matching Israel location rules | 29 |
| Postings matching role-title rules | 14 |
| Postings flagged for role review | 1 |

The database load and both report exports completed successfully.
Posting counts can change between runs.

## Interpretation and limitations

- Coverage is limited to configured boards or the first page of each JSearch
  query. Neither mode represents the entire Israeli job market.
- Location matching uses a limited set of text rules and may miss
  other location formats.
- Role and seniority labels are title-based heuristics. Candidate rules also
  recognize a limited set of English experience statements. Missing or
  unsupported experience wording is not interpreted as zero experience.
- Candidate labels do not establish eligibility. Conflicting senior/entry
  signals, alternative requirements, and uncertain roles require review.
  All qualifications still need to be read before applying.
- Technology detection uses a configured keyword dictionary.
  Mentions do not necessarily indicate mandatory requirements.
- The chart summarizes the latest collection per board. Historical trend
  visualization has not yet been implemented.

## Offline checks

Run from the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The checks use synthetic postings, mocked API calls, and temporary
databases and reports. They cover older snapshots loaded later,
zero-match boards, overlapping posting IDs across boards, empty
descriptions, missing sources, and failures before report generation.

## Automation

The pipeline runs through GitHub Actions using
[the workflow configuration](.github/workflows/job_market_etl.yml).

- Scheduled daily at 06:17 UTC.
- Supports manual execution from Actions → Daily Job Market ETL → Run workflow.
- Runs on GitHub infrastructure, independently of the local computer.
- Runs the offline checks before collecting live data.
- Commits the updated SQLite database, all three CSV reports, and chart to `main`
  after a successful pipeline run.
- Retains raw JSON snapshots as downloadable workflow artifacts for 14 days.
- Prevents simultaneous executions of this workflow.

Scheduled runs may be delayed by GitHub Actions.

The first manual GitHub Actions run completed successfully.
Its output commit was pulled locally, confirming that the new
collection was added while previous collection history was preserved.

Scheduled execution of the initial Similarweb version was verified
on 2026-10-15.
Two runs triggered by `schedule` completed successfully, and their
database and report updates were pulled into the local repository.

## Continuing local development

Before editing or running the project locally, synchronize the
latest automated updates with `git pull --ff-only`.

This keeps the local database and reports aligned with the
latest successful GitHub Actions run.

## Planned extensions

- Expand the monitored company set after checking source data quality.
- Evaluate candidate classification against manually reviewed postings,
  including Hebrew requirements and more complex experience alternatives.
- Visualize changes across collection dates.
