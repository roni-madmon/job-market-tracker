import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from database import initialize_database
from job_rules import classify_jobs
from transform import filter_israel_jobs, transform_jobs


JOB_COLUMNS = [
    "posting_id", "job_title", "company", "location", "job_url",
    "description_html", "source_updated_at", "source_first_published_at",
    "country", "location_match_method", "job_family",
    "role_match_status", "seniority_hint",
]


def load_jobs(
    df: pd.DataFrame,
    snapshot: dict,
    raw_file_name: str,
    database_path: Path,
) -> int:
    """Save classified Israel postings for one collection atomically.

    Args:
        df: All Israel postings with their classification columns.
        snapshot: Raw postings and their collection metadata.
        raw_file_name: Name of the source JSON file.
        database_path: Path to the initialized SQLite database.

    Returns:
        Collection ID, reused when processing the same snapshot again.

    Raises:
        ValueError: If counts, identifiers or source metadata are invalid.
        KeyError: If required fields or columns are missing.
        sqlite3.DatabaseError: If a database operation fails.
    """
    if snapshot["job_count"] != len(snapshot["jobs"]):
        raise ValueError("Snapshot job_count does not match its records.")

    if len(df) > snapshot["job_count"]:
        raise ValueError("Processed count exceeds the raw posting count.")

    collection_key = (
        snapshot["source"],
        snapshot["board_token"],
        snapshot["saved_at_utc"],
    )

    metadata_columns = [
        "source", "board_token", "snapshot_saved_at_utc",
    ]
    for column, expected in zip(metadata_columns, collection_key):
        if not df[column].eq(expected).fillna(False).all():
            raise ValueError(f"Snapshot metadata mismatch: {column}")

    # These database columns are TEXT; preserve missing values as SQL NULL.
    data = df[JOB_COLUMNS].astype("string")
    for column in ["posting_id", "job_title", "job_url"]:
        if data[column].fillna("").str.strip().eq("").any():
            raise ValueError(f"Missing or blank required value: {column}")

    data["posting_id"] = data["posting_id"].str.strip()
    if data["posting_id"].duplicated().any():
        raise ValueError("Duplicate posting_id values in this collection.")

    records = (
        data.astype(object)
        .where(data.notna(), None)
        .to_dict(orient="records")
    )
    processed_at = datetime.now(timezone.utc).isoformat()

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        # Commit the collection and all its postings together, or roll back.
        with connection:
            connection.execute(
                """
                INSERT INTO collection_runs (
                    source, board_token, snapshot_saved_at_utc,
                    raw_file_name, raw_posting_count,
                    israel_posting_count, last_processed_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    source, board_token, snapshot_saved_at_utc
                )
                DO UPDATE SET
                    raw_file_name = excluded.raw_file_name,
                    raw_posting_count = excluded.raw_posting_count,
                    israel_posting_count = excluded.israel_posting_count,
                    last_processed_at_utc = excluded.last_processed_at_utc
                """,
                (
                    *collection_key, raw_file_name,
                    snapshot["job_count"], len(df), processed_at,
                ),
            )

            collection_id = connection.execute(
                """
                SELECT collection_id
                FROM collection_runs
                WHERE source = ?
                  AND board_token = ?
                  AND snapshot_saved_at_utc = ?
                """,
                collection_key,
            ).fetchone()[0]

            for record in records:
                record["collection_id"] = collection_id

            # Refresh only this collection; retain other collection dates.
            connection.execute(
                "DELETE FROM job_snapshots WHERE collection_id = ?",
                (collection_id,),
            )
            connection.executemany(
                """
                INSERT INTO job_snapshots (
                    collection_id, posting_id, job_title, company,
                    location, job_url, description_html,
                    source_updated_at, source_first_published_at,
                    country, location_match_method, job_family,
                    role_match_status, seniority_hint
                )
                VALUES (
                    :collection_id, :posting_id, :job_title, :company,
                    :location, :job_url, :description_html,
                    :source_updated_at, :source_first_published_at,
                    :country, :location_match_method, :job_family,
                    :role_match_status, :seniority_hint
                )
                """,
                records,
            )

    return collection_id


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent
    snapshot_files = sorted(
        (project_dir / "data" / "raw").glob("similarweb_*.json")
    )
    if not snapshot_files:
        raise FileNotFoundError("No Similarweb snapshots found.")

    latest_snapshot = snapshot_files[-1]
    with latest_snapshot.open(encoding="utf-8") as file:
        snapshot = json.load(file)

    jobs_df = transform_jobs(snapshot)
    israel_jobs_df = filter_israel_jobs(jobs_df)
    classified_df = classify_jobs(israel_jobs_df)

    database_path = initialize_database()
    collection_id = load_jobs(
        classified_df, snapshot, latest_snapshot.name, database_path,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM collection_runs),
                (SELECT COUNT(*) FROM job_snapshots)
            """
        ).fetchone()

        statuses = connection.execute(
            """
            SELECT role_match_status, COUNT(*)
            FROM job_snapshots
            WHERE collection_id = ?
            GROUP BY role_match_status
            ORDER BY role_match_status
            """,
            (collection_id,),
        ).fetchall()

    print(f"Input file: {latest_snapshot.name}")
    print(f"Collection ID: {collection_id}")
    print(f"collection_runs: {counts[0]} rows")
    print(f"job_snapshots: {counts[1]} rows")
    print("\nStored role statuses for this collection:")
    for status, count in statuses:
        print(f"{status}: {count}")