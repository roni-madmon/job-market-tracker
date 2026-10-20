import json
import logging
import os
from pathlib import Path
import argparse
from config import GREENHOUSE_BOARDS
from database import initialize_database
from extract import extract_jobs
from job_rules import classify_jobs
from load import load_jobs
from raw_storage import save_raw_jobs
from transform import filter_israel_jobs, transform_jobs
from visualize import generate_reports

logger = logging.getLogger(__name__)


def collect_board(board_token: str, database_path: Path) -> int:
    """Collect, classify and store one company board.

    Saves the raw data before transformation. All subsequent stages
    use the collection metadata from that saved snapshot.
    Errors propagate to the command-line entry point.

    Args:
        board_token: Identifier of the Greenhouse board to collect.
        database_path: Initialized SQLite database for collection history.

    Returns:
        Identifier of the collection stored in SQLite.
    """
    # Extract: retrieve postings and preserve the raw response records.
    jobs = extract_jobs(board_token)
    logger.info("[%s] Extracted postings: %d", board_token, len(jobs))

    snapshot_path = save_raw_jobs(jobs, board_token=board_token)
    logger.info("Raw snapshot saved: %s", snapshot_path.name)

    with snapshot_path.open(encoding="utf-8") as file:
        snapshot = json.load(file)

    # Transform: normalize fields, filter locations and classify titles.
    jobs_df = transform_jobs(snapshot)
    israel_jobs_df = filter_israel_jobs(jobs_df)
    classified_df = classify_jobs(israel_jobs_df)

    logger.info("[%s] Israel postings: %d", board_token, len(classified_df))
    logger.info(
        "[%s] Title-rule matches: %d", board_token,
        classified_df["role_match_status"].eq("matched").sum(),
    )
    logger.info(
        "[%s] Needs review: %d", board_token,
        classified_df["role_match_status"].eq("needs_review").sum(),
    )

    # Load: save this collection and its postings in one transaction.
    collection_id = load_jobs(
        classified_df,
        snapshot,
        snapshot_path.name,
        database_path,
    )
    logger.info("[%s] Collection ID: %d", board_token, collection_id)
    return collection_id


def run_pipeline(source: str = "greenhouse") -> dict[str, int]:
    """Run the selected provider and generate its latest reports.

    Each board is stored in its own transaction. If any stage fails,
    the exception propagates and the run is not reported as successful.
    Previously committed collections remain available for inspection.

    Args:
        source: greenhouse (company boards) or jsearch (role-query batch).

    Returns:
        A mapping from board/query scope tokens to stored collection IDs.
    """
    if source == "jsearch":
        from search_pipeline import run_search_pipeline
        return run_search_pipeline()
    if source != "greenhouse":
        raise ValueError("JOB_SOURCE must be greenhouse or jsearch.")
    if not GREENHOUSE_BOARDS:
        raise ValueError("Configure at least one Greenhouse board.")

    logger.info("Starting job-market ETL pipeline.")
    database_path = initialize_database()
    collection_ids = {}

    for board_token, company in GREENHOUSE_BOARDS.items():
        logger.info("Collecting %s (%s).", company, board_token)
        collection_ids[board_token] = collect_board(
            board_token, database_path,
        )

    # Publish reports only after every requested board was collected.
    logger.info("Generating technology reports.")

    project_dir = Path(__file__).resolve().parent
    csv_path, chart_path, coverage_path = generate_reports(
        database_path=database_path,
        output_dir=project_dir / "reports",
        board_tokens=tuple(collection_ids),
    )

    logger.info("CSV report saved: %s", csv_path)
    logger.info("Chart saved: %s", chart_path)
    logger.info("Collection coverage saved: %s", coverage_path)
    logger.info("Classification report saved: %s", project_dir / "reports" / "job_classifications.csv")
    logger.info("Pipeline completed successfully.")

    return collection_ids
   

def cli() -> int:
    """Choose a data source and run collection or report generation."""

    parser = argparse.ArgumentParser(
        description="Collect Israel tech jobs and generate technology reports."
    )

    parser.add_argument(
        "--source",
        choices=("greenhouse", "jsearch"),
        help="Data source. Defaults to JOB_SOURCE or greenhouse.",
    )

    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Generate reports from saved data without calling an API.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show the full error traceback.",
    )

    args = parser.parse_args()

    source = (
        args.source or os.environ.get("JOB_SOURCE", "greenhouse")
    ).strip().lower()

    if source not in {"greenhouse", "jsearch"}:
        parser.error("JOB_SOURCE must be greenhouse or jsearch.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    logger.info("Selected source: %s", source)

    try:
        if args.report_only:
            project_dir = Path(__file__).resolve().parent

            generate_reports(
                database_path=project_dir / "data" / "job_market.sqlite3",
                output_dir=project_dir / "reports",
                source=source,
                candidate_only=source == "jsearch",
            )

            logger.info(
                "Reports refreshed from saved data. No jobs fetched."
            )
        else:
            run_pipeline(source=source)

        logger.info("Reports are ready in the reports folder.")
        return 0

    except Exception as error:
        if args.debug:
            logger.exception("Run failed.")
        else:
            logger.error("Run failed: %s", error)
            logger.error("Use --debug for the full traceback.")

        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
