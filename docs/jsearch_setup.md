# Role-based search and daily automation

JSearch searches across employers instead of a fixed company list. This
implementation requests Data Student, Software Student, and DevOps Student
jobs in Israel, with one page for each query. Change JSEARCH_QUERIES in
config.py to change that scope. A scope change should also receive a new
JSEARCH_SCOPE version so historical query sets remain distinguishable.

The extractor uses GET /search-v2 and reads postings from data.jobs.
It omits cursor to start at the first page and does not follow returned
cursors. Every query explicitly sets country=il and language=en. In the
RapidAPI playground, set country to il as well: the default may be us,
even if the search text contains Israel. HTTP 200 confirms request success;
an empty jobs list does not establish that no matching jobs exist elsewhere.

## 1. Choose an API gateway and obtain your own key

- Direct provider: [OpenWeb Ninja JSearch](https://www.openwebninja.com/api/jsearch).
  The code defaults to this route. Select the Free plan and inspect its
  current request allowance in the provider portal.
- If you already use [JSearch through RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch),
  set JSEARCH_PROVIDER to rapidapi. A key belongs to its gateway and cannot
  be exchanged between the two providers.

There are three API requests per complete run, one page per query. Daily
runs use at most 93 search requests in a 31-day month, plus any manual
runs. The code does not purchase plans, paginate further, or retry paid
requests automatically. Provider rate limits and quotas still apply.

Do not put the key in source files or commit it. Never paste it into chat.

## 2. Run offline checks before using an API key

In PowerShell, from C:\project\job-market-tracker:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The checks use mock responses and temporary databases. Passing tests is
not evidence that the real JSearch account is activated or has quota.

## 3. Run one local search

These are PowerShell commands. The key prompt masks input and does not
place the value in the command history. The variables last for this
terminal session only. Set the provider before running the pipeline.

```powershell
$env:JOB_SOURCE = "jsearch"
$env:JSEARCH_PROVIDER = "openwebninja"
$jobTrackerKey = Read-Host "Paste your JSearch API key" -AsSecureString
$env:JSEARCH_API_KEY = [System.Net.NetworkCredential]::new("", $jobTrackerKey).Password
.\.venv\Scripts\python.exe main.py
```

Use rapidapi instead of openwebninja only for a RapidAPI key.
The program should log three queries, a JSearch collection ID, report paths,
and successful completion. A missing key, provider error, malformed response,
or failed query must fail the run. Zero returned jobs can be a valid result.

For a failed HTTP request, the error includes the provider's message with
the configured API key redacted. If RapidAPI reports no subscription,
check that JSearch BASIC is active for the account owning the selected key.
If the playground succeeds but Python fails, compare its request URL and
selected application with the local /search-v2 route and key. Do not paste
the key or request headers into chat or commit them.

Inspect reports in PowerShell:

```powershell
Import-Csv .\reports\collection_coverage.csv | Format-List
Import-Csv .\reports\job_classifications.csv |
    Select-Object company, job_title, job_family, opportunity_status, classification_reason |
    Format-List
```

## 4. Understand the classifications

| Status | Meaning |
| --- | --- |
| student_candidate | Relevant role with an explicit student/intern signal |
| junior_candidate | Relevant role with a junior/graduate title |
| entry_level_candidate | Relevant role with explicit no-experience or 0-2-year evidence |
| experienced | Senior title or a recognized experience requirement above two years |
| needs_review | Role/seniority is unclear, requirements are alternatives, or signals conflict |
| out_of_scope | No configured role-family match |

Candidate means worth reviewing, not confirmed eligibility. Numeric matching
is a limited English rule set. Unsupported wording, Hebrew requirements,
degree alternatives, and mixed mandatory/preferred clauses can require
manual review. Company history is not treated as applicant experience.

The classification CSV contains every Israel posting in the selected batch,
including excluded and uncertain jobs, URLs, reasons, evidence, and the rule
version. The JSearch technology chart uses only the three candidate statuses.
An unknown seniority is never automatically converted into a junior label.

All queries form one JSearch collection. The coverage CSV therefore has one
row for the search batch, with the provider's query-scope identifier in the
legacy board_token field. The company field is a batch label. Actual employer
names are in job_classifications.csv. This is not a count of monitored companies.

## 5. Enable the existing daily workflow for JSearch

First commit and push the new source files, tests, documentation and workflow.
Then, in the GitHub repository, open Settings, Secrets and variables, Actions.

1. In Secrets, choose New repository secret. Name: JSEARCH_API_KEY.
   Value: your personal API key. Choose Add secret.
2. In Variables, choose New repository variable. Name: JSEARCH_PROVIDER.
   Value: openwebninja (or rapidapi for a RapidAPI key).
3. Create another repository variable. Name: JOB_SOURCE. Value: jsearch.
4. Open Actions, Daily Job Market ETL, Run workflow. Select main and run once.

The existing schedule stays at 06:17 UTC. The same workflow runs tests,
collects the selected source, stores raw snapshots as artifacts, and commits
the database plus all three CSV reports and the chart after success.
Without JOB_SOURCE the default remains Greenhouse; JSearch is enabled
explicitly so a repository without a configured key keeps its current mode.

Repository variables do not set environment variables on your Windows PC.
Keep JOB_SOURCE=jsearch in the local terminal when regenerating JSearch reports.
Switching back to greenhouse preserves both providers' database histories,
but the latest report files always describe only the selected provider.

After a successful cloud run, synchronize the bot's updates locally:

```powershell
git pull --ff-only
git status
```

References:
- [JSearch provider documentation](https://www.openwebninja.com/api/jsearch/docs)
- [GitHub repository secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [GitHub repository variables](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables)

## Verification status of this change

The original scheduled Greenhouse runs were verified on 2026-10-15.
This JSearch extension has offline integration checks. It still needs a
real run with the repository owner's key and a successful Actions run
before live JSearch collection can be claimed as verified.
