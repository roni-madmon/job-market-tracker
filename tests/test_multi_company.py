"""Offline integration checks using synthetic job postings."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import main
import raw_storage
from config import GREENHOUSE_BOARDS
from job_rules import classify_jobs
from load import load_jobs
from skill_analysis import read_latest_matched_jobs
from transform import filter_israel_jobs, transform_jobs
from visualize import generate_reports


class MultiCompanyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database_path = self.root / "jobs.sqlite3"
        schema_path = Path(__file__).resolve().parents[1] / "schema.sql"
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.executescript(schema_path.read_text(encoding="utf-8-sig"))

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def job(token, posting_id, title, description="<p>Python SQL</p>"):
        return {
            "id": posting_id,
            "title": title,
            "company_name": GREENHOUSE_BOARDS[token],
            "absolute_url": f"https://example.invalid/{token}/{posting_id}",
            "location": {"name": "Tel Aviv, Israel"},
            "content": description,
        }

    def store(self, token, timestamp, jobs):
        snapshot = {
            "source": "greenhouse",
            "board_token": token,
            "saved_at_utc": timestamp,
            "job_count": len(jobs),
            "jobs": jobs,
        }
        classified = classify_jobs(filter_israel_jobs(transform_jobs(snapshot)))
        return load_jobs(
            classified, snapshot, f"{token}_fixture.json", self.database_path,
        )

    def seed_history(self):
        self.store("similarweb", "2024-01-02T10:00:00+00:00", [
            self.job("similarweb", 1, "Data Analyst", "<p>AWS</p>"),
        ])
        similarweb_latest = self.store(
            "similarweb", "2024-01-03T10:00:00+00:00", [
                self.job("similarweb", 101, "Data Analyst", "Python Python SQL"),
            ],
        )
        # A backfill gets a higher collection ID but has an older timestamp.
        self.store("similarweb", "2024-01-01T10:00:00+00:00", [
            self.job("similarweb", 2, "Data Engineer", "<p>AWS</p>"),
        ])
        self.store("forter", "2024-01-02T10:00:00+00:00", [
            self.job("forter", 1, "Data Analyst", "<p>AWS</p>"),
        ])
        forter_latest = self.store(
            "forter", "2024-01-03T10:01:00+00:00", [
                self.job("forter", 11, "Recovery Analyst Student"),
                self.job("forter", 12, "General Application (Israel)"),
            ],
        )
        gong_latest = self.store("gongio", "2024-01-03T10:02:00+00:00", [
            self.job("gongio", 101, "Senior Data Scientist", "<p>SQL</p>"),
            self.job("gongio", 102, "Data Engineer", None),
        ])
        return {
            "similarweb": similarweb_latest,
            "forter": forter_latest,
            "gongio": gong_latest,
        }

    def test_latest_per_board_preserves_zero_matches_and_board_identity(self):
        expected_ids = self.seed_history()
        collections, jobs = read_latest_matched_jobs(self.database_path)
        self.assertEqual(
            collections.set_index("board_token")["collection_id"].to_dict(),
            expected_ids,
        )
        self.assertEqual(
            collections.set_index("board_token")["matched_posting_count"].to_dict(),
            {"similarweb": 1, "forter": 0, "gongio": 2},
        )
        self.assertEqual(len(jobs), 3)
        self.assertEqual(
            set(jobs.loc[jobs.posting_id.eq("101"), "board_token"]),
            {"similarweb", "gongio"},
        )

    def test_report_denominator_and_coverage(self):
        self.seed_history()
        csv_path, chart_path, coverage_path = generate_reports(
            self.database_path, self.root / "reports",
        )
        report = pd.read_csv(csv_path).set_index("technology")
        coverage = pd.read_csv(coverage_path).set_index("board_token")
        self.assertEqual(set(report.index), {"Python", "SQL"})
        self.assertEqual(report.loc["Python", "posting_count"], 1)
        self.assertEqual(report.loc["SQL", "posting_count"], 2)
        self.assertEqual(report.loc["SQL", "posting_share_pct"], 66.7)
        self.assertTrue(report["analyzed_posting_count"].eq(3).all())
        self.assertTrue(report["empty_description_count"].eq(1).all())
        self.assertTrue(report["monitored_board_count"].eq(3).all())
        self.assertTrue(report["contributing_board_count"].eq(2).all())
        self.assertEqual(coverage.loc["forter", "matched_posting_count"], 0)
        self.assertEqual(coverage.loc["gongio", "empty_description_count"], 1)
        self.assertTrue(chart_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_empty_latest_collections_keep_coverage(self):
        self.seed_history()
        for token in GREENHOUSE_BOARDS:
            self.store(token, "2024-01-04T10:00:00+00:00", [])
        csv_path, chart_path, coverage_path = generate_reports(
            self.database_path, self.root / "reports",
        )
        self.assertTrue(pd.read_csv(csv_path).empty)
        coverage = pd.read_csv(coverage_path)
        self.assertEqual(len(coverage), 3)
        self.assertTrue(coverage["matched_posting_count"].eq(0).all())
        self.assertTrue(chart_path.is_file())

    def test_missing_board_cannot_silently_reduce_report_scope(self):
        self.store("similarweb", "2024-01-03T10:00:00+00:00", [])
        with self.assertRaisesRegex(ValueError, "forter, gongio"):
            generate_reports(self.database_path, self.root / "reports")
        self.assertFalse((self.root / "reports").exists())

    def test_pipeline_collects_all_boards_and_preserves_history(self):
        previous_id = self.store("similarweb", "2020-01-01T00:00:00+00:00", [
            self.job("similarweb", 999, "Data Analyst", "AWS"),
        ])
        payloads = {
            "similarweb": [self.job("similarweb", 101, "Data Analyst")],
            "forter": [self.job("forter", 201, "Recovery Analyst Student")],
            "gongio": [self.job("gongio", 301, "Senior Data Scientist")],
        }
        with (
            patch.object(main, "initialize_database", return_value=self.database_path),
            patch.object(main, "extract_jobs", side_effect=payloads.__getitem__) as fetch,
            patch.object(main, "__file__", str(self.root / "main.py")),
            patch.object(raw_storage, "__file__", str(self.root / "raw_storage.py")),
        ):
            collection_ids = main.run_pipeline()
        self.assertEqual(list(collection_ids), list(GREENHOUSE_BOARDS))
        self.assertEqual(
            [call.args[0] for call in fetch.call_args_list],
            list(GREENHOUSE_BOARDS),
        )
        self.assertEqual(len(list((self.root / "data" / "raw").glob("*.json"))), 3)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0],
                4,
            )
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM job_snapshots WHERE collection_id = ?",
                (previous_id,),
            ).fetchone()[0], 1)
        coverage = pd.read_csv(self.root / "reports" / "collection_coverage.csv")
        self.assertEqual(
            coverage.set_index("board_token")["collection_id"].to_dict(),
            collection_ids,
        )

    def test_failed_board_prevents_report_generation(self):
        with (
            patch.object(main, "initialize_database", return_value=self.database_path),
            patch.object(main, "extract_jobs", side_effect=[
                [self.job("similarweb", 101, "Data Analyst")],
                ConnectionError("Synthetic source failure"),
            ]),
            patch.object(raw_storage, "__file__", str(self.root / "raw_storage.py")),
            patch.object(main, "generate_reports") as report,
        ):
            with self.assertRaisesRegex(ConnectionError, "Synthetic source failure"):
                main.run_pipeline()
        report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
