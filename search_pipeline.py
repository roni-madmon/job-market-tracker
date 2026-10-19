"""Collect a complete JSearch query set before publishing its reports."""

import json
import logging
from pathlib import Path

from config import JSEARCH_SCOPE
from database import initialize_database
from extract_search import extract_search_jobs
from job_rules import classify_jobs
from load import load_jobs
from raw_storage import save_raw_jobs
from transform import filter_israel_jobs, transform_jobs
from visualize import generate_reports


logger = logging.getLogger(__name__)


def run_search_pipeline() -> dict[str, int]:
    """Collect query-based jobs across employers and preserve source history."""
    jobs, search_context = extract_search_jobs()
    raw_path = save_raw_jobs(
        jobs, board_token=JSEARCH_SCOPE, source="jsearch", context=search_context,
    )
    logger.info("[jsearch] Raw snapshot saved: %s", raw_path.name)
    snapshot = json.loads(raw_path.read_text(encoding="utf-8"))
    normalized = transform_jobs(snapshot)
    classified = classify_jobs(filter_israel_jobs(normalized))
    logger.info("[jsearch] Raw records across queries: %d", len(jobs))
    logger.info("[jsearch] Distinct postings after normalization: %d", len(normalized))
    logger.info("[jsearch] Israel postings: %d", len(classified))
    database_path = initialize_database()
    collection_id = load_jobs(classified, snapshot, raw_path.name, database_path)
    logger.info("[jsearch] Collection ID: %d", collection_id)
    project_dir = Path(__file__).resolve().parent
    paths = generate_reports(
        database_path, project_dir / "reports",
        board_tokens=(JSEARCH_SCOPE,), source="jsearch", candidate_only=True,
    )
    for path in paths:
        logger.info("Report saved: %s", path)
    logger.info("Classification report saved: %s", project_dir / "reports" / "job_classifications.csv")
    logger.info("Pipeline completed successfully.")
    return {JSEARCH_SCOPE: collection_id}
