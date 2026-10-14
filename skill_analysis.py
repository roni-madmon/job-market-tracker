import re
import sqlite3
from contextlib import closing
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd


SKILL_RULES = {
    "Python": r"\bpython\b",
    "SQL": r"\bsql\b",
    "Excel": r"\bexcel\b",
    "Power BI": r"\bpower\s*bi\b",
    "Tableau": r"\btableau\b",
    "Looker": r"\blooker\b",
    "Pandas": r"\bpandas\b",
    "NumPy": r"\bnumpy\b",
    "Spark": r"\b(?:spark|pyspark)\b",
    "Airflow": r"\bairflow\b",
    "dbt": r"\bdbt\b",
    "Snowflake": r"\bsnowflake\b",
    "Databricks": r"\bdatabricks\b",
    "BigQuery": r"\bbigquery\b",
    "AWS": r"\b(?:aws|amazon\s+web\s+services)\b",
    "Azure": r"\bazure\b",
    "GCP": r"\b(?:gcp|google\s+cloud(?:\s+platform)?)\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\b(?:kubernetes|k8s)\b",
    "PyTorch": r"\bpytorch\b",
    "TensorFlow": r"\btensorflow\b",
    "Scikit-learn": r"\b(?:scikit[\s-]*learn|sklearn)\b",
    "Java": r"\bjava\b",
    "JavaScript": r"\bjavascript\b",
    "C++": r"(?<![\w+])c\+\+(?![\w+])",
}


class _DescriptionParser(HTMLParser):
    """Collect text while excluding HTML markup, scripts and styles."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored_tag = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored_tag = tag

    def handle_endtag(self, tag):
        if tag == self.ignored_tag:
            self.ignored_tag = None

    def handle_data(self, data):
        if self.ignored_tag is None:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    """Convert a job description into whitespace-normalized plain text."""
    if not isinstance(value, str):
        return ""

    parser = _DescriptionParser()
    parser.feed(unescape(value))
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def extract_skills(text: str) -> list[str]:
    """Return each configured technology at most once per posting.

    Matches indicate textual mentions, not confirmed requirements.
    Only technologies covered by SKILL_RULES can be detected.
    """
    return [
        skill
        for skill, pattern in SKILL_RULES.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]


def read_latest_matched_jobs(
    database_path: Path,
) -> tuple[dict, pd.DataFrame]:
    """Read matched Israel postings from the latest Similarweb collection.

    Returns:
        Collection metadata and a DataFrame of matched postings.

    Raises:
        FileNotFoundError: If the database does not exist.
        ValueError: If no Similarweb collection has been stored.
    """
    if not database_path.is_file():
        raise FileNotFoundError("Database not found. Run main.py first.")

    database_uri = database_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row

        collection = connection.execute(
            """
            SELECT collection_id, source, board_token,
                   snapshot_saved_at_utc
            FROM collection_runs
            WHERE source = ? AND board_token = ?
            ORDER BY snapshot_saved_at_utc DESC, collection_id DESC
            LIMIT 1
            """,
            ("greenhouse", "similarweb"),
        ).fetchone()

        if collection is None:
            raise ValueError("No Similarweb collection found.")

        jobs = pd.read_sql_query(
            """
            SELECT posting_id, job_title, description_html
            FROM job_snapshots
            WHERE collection_id = ?
              AND country = 'Israel'
              AND role_match_status = 'matched'
            ORDER BY job_title, posting_id
            """,
            connection,
            params=(collection["collection_id"],),
        )

    return dict(collection), jobs


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent
    database_path = project_dir / "data" / "job_market.sqlite3"

    collection, jobs_df = read_latest_matched_jobs(database_path)

    jobs_df["description_text"] = jobs_df["description_html"].map(
        html_to_text
    )
    jobs_df["skills"] = jobs_df["description_text"].map(extract_skills)

    counts = (
        jobs_df["skills"]
        .explode()
        .dropna()
        .value_counts()
        .rename_axis("technology")
        .rename("posting_count")
    )

    print(f"Collection ID: {collection['collection_id']}")
    print(f"Collected at (UTC): {collection['snapshot_saved_at_utc']}")
    print(f"Matched postings analyzed: {len(jobs_df)}")
    print(
        "Empty descriptions: "
        f"{jobs_df['description_text'].eq('').sum()}"
    )

    print("\nPostings mentioning each technology:")
    print(counts.to_string() if not counts.empty else "No matches found.")

    print("\nSample postings:")
    sample = jobs_df[["job_title", "skills"]].head(5).copy()
    sample["skills"] = sample["skills"].map(", ".join)
    print(sample.to_string(index=False))