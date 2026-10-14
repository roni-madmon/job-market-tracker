import json
import logging
from pathlib import Path

from database import initialize_database
from extract import extract_jobs
from job_rules import classify_jobs
from load import load_jobs
from raw_storage import save_raw_jobs
from transform import filter_israel_jobs, transform_jobs
from visualize import generate_reports

logger = logging.getLogger(__name__)


def run_pipeline() -> int:
    """Collect, process and store one snapshot of job postings.

    Saves the raw data before transformation. All subsequent stages
    use the collection metadata from that saved snapshot.
    Errors propagate to the command-line entry point.

    Returns:
        Identifier of the collection stored in SQLite.
    """
    logger.info("Starting job-market ETL pipeline.")

    # Extract: retrieve postings and preserve the raw response records.
    jobs = extract_jobs()
    logger.info("Extracted postings: %d", len(jobs))

    snapshot_path = save_raw_jobs(jobs, board_token="similarweb")
    logger.info("Raw snapshot saved: %s", snapshot_path.name)

    with snapshot_path.open(encoding="utf-8") as file:
        snapshot = json.load(file)

    # Transform: normalize fields, filter locations and classify titles.
    jobs_df = transform_jobs(snapshot)
    israel_jobs_df = filter_israel_jobs(jobs_df)
    classified_df = classify_jobs(israel_jobs_df)

    logger.info("Israel postings: %d", len(classified_df))
    logger.info(
        "Title-rule matches: %d",
        classified_df["role_match_status"].eq("matched").sum(),
    )
    logger.info(
        "Needs review: %d",
        classified_df["role_match_status"].eq("needs_review").sum(),
    )

    # Load: save this collection and its postings in one transaction.
    database_path = initialize_database()
    collection_id = load_jobs(
        classified_df,
        snapshot,
        snapshot_path.name,
        database_path,
    )
    logger.info("Collection ID: %d", collection_id)
    logger.info("Loaded Israel postings: %d", len(classified_df))

    # Generate reports after the collection has been saved successfully.
    logger.info("Generating technology reports.")

    project_dir = Path(__file__).resolve().parent
    csv_path, chart_path = generate_reports(
        database_path=database_path,
        output_dir=project_dir / "reports",
    )

    logger.info("CSV report saved: %s", csv_path)
    logger.info("Chart saved: %s", chart_path)
    logger.info("Pipeline completed successfully.")

    return collection_id
   

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    try:
        run_pipeline()
    except Exception:
        logger.exception("Pipeline failed.")
        raise SystemExit(1)
    