"""Offline provider, classification, and persistence contract checks."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

import extract_search
import main
import raw_storage
import search_pipeline
from config import JSEARCH_QUERIES, JSEARCH_SCOPE
from job_rules import classify_jobs
from opportunity_rules import classify_opportunities
from skill_analysis import read_latest_jobs
from transform import filter_israel_jobs, transform_jobs
from visualize import generate_reports


def job(identifier, title="Data Analyst Student", description="Python SQL", country="IL"):
    return {
        "job_id": identifier, "job_title": title, "employer_name": "Synthetic employer",
        "job_description": description, "job_country": country, "job_city": "Haifa",
        "job_location": "Haifa", "job_apply_link": f"https://example.invalid/jobs/{identifier}",
    }


def response(jobs, cursor=None):
    result = Mock()
    result.json.return_value = {"status": "OK", "data": {"jobs": jobs, "cursor": cursor}}
    return result


class JSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database_path = self.root / "jobs.sqlite3"
        schema = Path(__file__).resolve().parents[1] / "schema.sql"
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.executescript(schema.read_text(encoding="utf-8"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_queries_are_bounded_and_raw_duplicates_are_preserved(self):
        with (
            patch.dict(os.environ, {"JSEARCH_API_KEY": "synthetic-test-key"}, clear=True),
            patch.object(extract_search.requests, "get", side_effect=[response([job("same")], cursor="more-results-available") for _ in JSEARCH_QUERIES]) as get,
        ):
            jobs, context = extract_search.extract_search_jobs()
        self.assertEqual(len(jobs), 3)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.kwargs["params"]["query"] for call in get.call_args_list], list(JSEARCH_QUERIES))
        for call in get.call_args_list:
            self.assertEqual(call.args[0], "https://api.openwebninja.com/jsearch/search-v2")
            self.assertEqual(call.kwargs["params"]["country"], "il")
            self.assertEqual(call.kwargs["params"]["num_pages"], 1)
            self.assertNotIn("page", call.kwargs["params"])
            self.assertNotIn("cursor", call.kwargs["params"])
            self.assertEqual(call.kwargs["timeout"], 30)
        self.assertEqual(context["endpoint"], "/search-v2")
        self.assertNotIn("synthetic-test-key", json.dumps(context))

    def test_rapidapi_keys_are_sent_to_the_correct_gateway(self):
        with (
            patch.dict(os.environ, {"JSEARCH_API_KEY": "synthetic-test-key", "JSEARCH_PROVIDER": "rapidapi"}, clear=True),
            patch.object(extract_search.requests, "get", return_value=response([])) as get,
        ):
            extract_search.extract_search_jobs()
        self.assertEqual(get.call_args.args[0], "https://jsearch.p.rapidapi.com/search-v2")
        self.assertEqual(get.call_args.kwargs["headers"]["x-rapidapi-host"], "jsearch.p.rapidapi.com")

    def test_http_errors_explain_failure_without_exposing_the_key(self):
        cases = [
            ({"message": "You are not subscribed to this API."}, "not subscribed"),
            ({"error": {"message": "Rejected key synthetic-test-key"}}, "[REDACTED]"),
            (None, "unsuccessful HTTP response"),
        ]
        for payload, expected in cases:
            failed = Mock(status_code=403)
            failed.raise_for_status.side_effect = requests.HTTPError("Original error")
            if payload is None:
                failed.json.side_effect = ValueError("Not JSON")
            else:
                failed.json.return_value = payload
            with (
                self.subTest(payload=payload),
                patch.dict(os.environ, {"JSEARCH_API_KEY": "synthetic-test-key", "JSEARCH_PROVIDER": "rapidapi"}, clear=True),
                patch.object(extract_search.requests, "get", return_value=failed) as get,
                patch.object(search_pipeline, "save_raw_jobs") as save,
                patch.object(search_pipeline, "initialize_database") as initialize,
                patch.object(search_pipeline, "generate_reports") as report,
            ):
                with self.assertRaises(requests.HTTPError) as caught:
                    main.run_pipeline(source="jsearch")
            message = str(caught.exception)
            self.assertIn("403", message)
            self.assertIn(expected, message)
            self.assertNotIn("synthetic-test-key", message)
            self.assertEqual(get.call_count, 1)
            save.assert_not_called()
            initialize.assert_not_called()
            report.assert_not_called()

    def test_missing_key_and_invalid_provider_make_no_requests(self):
        for environment in ({}, {"JSEARCH_API_KEY": "synthetic-test-key", "JSEARCH_PROVIDER": "invalid"}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True), patch.object(extract_search.requests, "get") as get:
                with self.assertRaises(ValueError):
                    extract_search.extract_search_jobs()
                get.assert_not_called()

    def test_failed_query_does_not_publish_partial_results(self):
        with (
            patch.dict(os.environ, {"JSEARCH_API_KEY": "synthetic-test-key"}, clear=True),
            patch.object(extract_search.requests, "get", side_effect=[response([job("1")]), requests.HTTPError("Synthetic quota failure")]) as get,
            patch.object(search_pipeline, "save_raw_jobs") as save,
            patch.object(search_pipeline, "initialize_database") as initialize,
            patch.object(search_pipeline, "generate_reports") as report,
        ):
            with self.assertRaises(requests.HTTPError):
                main.run_pipeline(source="jsearch")
        self.assertEqual(get.call_count, 2)
        save.assert_not_called()
        initialize.assert_not_called()
        report.assert_not_called()

    def test_malformed_responses_are_not_reported_as_empty_success(self):
        for payload in (
            {"status": "ERROR", "data": {"jobs": []}},
            {"status": "OK"},
            {"status": "OK", "data": {}},
            {"status": "OK", "data": []},
            {"status": "OK", "data": {"jobs": None}},
            {"status": "OK", "data": {"jobs": {}}},
            {"status": "OK", "data": {"jobs": [None]}},
        ):
            mock_response = response([])
            mock_response.json.return_value = payload
            with self.subTest(payload=payload), patch.dict(os.environ, {"JSEARCH_API_KEY": "synthetic-test-key"}, clear=True), patch.object(extract_search.requests, "get", return_value=mock_response):
                with self.assertRaises(ValueError):
                    extract_search.extract_search_jobs()

    def test_normalization_preserves_full_text_and_checks_country(self):
        long_text = "Description text. " * 100 + "PyTorch"
        jobs = [job("1", description=long_text), job("1"), job("2", country="US"), job("3")]
        jobs[2]["job_location"] = "Tel Aviv, US"
        snapshot = {"source": "jsearch", "board_token": JSEARCH_SCOPE, "saved_at_utc": "2024-01-01T00:00:00+00:00", "job_count": len(jobs), "jobs": jobs}
        normalized = transform_jobs(snapshot)
        self.assertEqual(len(normalized), 3)
        self.assertEqual(normalized.iloc[0]["description_html"], long_text)
        israel = filter_israel_jobs(normalized)
        self.assertEqual(set(israel["posting_id"]), {"1", "3"})
        self.assertTrue(israel["location_match_method"].eq("country_code").all())

    def test_classification_explains_candidates_conflicts_and_unknowns(self):
        cases = [
            ("Data Engineering Student", "Python", "student_candidate", "data_engineering"),
            ("Software Engineer Intern", "Java", "student_candidate", "software_engineering"),
            ("Software Engineering Student", "Java", "student_candidate", "software_engineering"),
            ("Junior DevOps Engineer", "Docker", "junior_candidate", "devops_cloud"),
            ("Data Analyst", "Requirements\n0-2 years of experience in SQL", "entry_level_candidate", "analytics_bi"),
            ("Data Analyst", "SQL", "needs_review", "analytics_bi"),
            ("Senior Data Engineer", "Python", "experienced", "data_engineering"),
            ("Junior Data Engineer", "Requirements\n5+ years of experience required", "needs_review", "data_engineering"),
            ("Data Engineer Student", "Nice to have\n5 years of experience", "student_candidate", "data_engineering"),
            ("Data Engineer Student", "Python knowledge is an advantage.\n5 years of experience required", "needs_review", "data_engineering"),
            ("Data Analyst Student", "Our company has 20 years of experience.", "student_candidate", "analytics_bi"),
            ("Data Analyst", "3 years of experience or equivalent education", "needs_review", "analytics_bi"),
            ("Recovery Analyst Student", "SQL", "needs_review", "unclassified"),
            ("Account Executive Student", "SQL", "out_of_scope", "unclassified"),
            ("Data Engineer", "This role requires no prior experience required.", "entry_level_candidate", "data_engineering"),
            ("Data Analyst Student", "Qualifications: 5 years of experience required; Python preferred", "needs_review", "analytics_bi"),
            ("Software Engineer", "We require applicants to be currently enrolled in a BSc.", "student_candidate", "software_engineering"),
        ]
        for title, description, status, family in cases:
            with self.subTest(title=title, description=description):
                frame = pd.DataFrame([{"job_title": title, "description_html": description}])
                classified = classify_opportunities(classify_jobs(frame)).iloc[0]
                self.assertEqual(classified["opportunity_status"], status)
                self.assertEqual(classified["job_family"], family)
                self.assertTrue(classified["classification_reason"])
                self.assertTrue(classified["classification_evidence"])

    def test_search_pipeline_preserves_history_and_reports_only_candidates(self):
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("INSERT INTO collection_runs (source,board_token,snapshot_saved_at_utc,raw_file_name,raw_posting_count,israel_posting_count,last_processed_at_utc) VALUES ('greenhouse','similarweb','2020-01-01T00:00:00+00:00','fixture.json',0,0,'2020-01-01T00:00:00+00:00')")
        replies = [
            response([job("shared"), job("unknown", "Data Analyst", "AWS")]),
            response([job("shared"), job("software", "Software Student", "Java"), job("foreign", country="US")]),
            response([job("senior", "Senior DevOps Engineer", "Kubernetes"), job("entry", "DevOps Engineer", "2 years of experience required. Docker")]),
        ]
        with (
            patch.dict(os.environ, {"JSEARCH_API_KEY": "synthetic-test-key"}, clear=True),
            patch.object(extract_search.requests, "get", side_effect=replies),
            patch.object(search_pipeline, "initialize_database", return_value=self.database_path),
            patch.object(search_pipeline, "__file__", str(self.root / "search_pipeline.py")),
            patch.object(raw_storage, "__file__", str(self.root / "raw_storage.py")),
        ):
            identifiers = main.run_pipeline(source="jsearch")
        self.assertEqual(set(identifiers), {JSEARCH_SCOPE})
        collections, jobs = read_latest_jobs(self.database_path, source="jsearch")
        self.assertEqual(len(collections), 1)
        self.assertEqual(len(jobs), 5)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0], 2)
        raw = json.loads(next((self.root / "data/raw").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(raw["job_count"], 7)
        self.assertEqual(len(raw["collection_context"]["query_results"]), 3)
        self.assertNotIn("synthetic-test-key", json.dumps(raw))
        report = pd.read_csv(self.root / "reports/technology_mentions.csv")
        self.assertEqual(set(report["technology"]), {"Python", "SQL", "Java", "Docker"})
        self.assertTrue(report["analyzed_posting_count"].eq(3).all())
        classifications = pd.read_csv(self.root / "reports/job_classifications.csv")
        self.assertEqual(len(classifications), 5)
        self.assertEqual(classifications.set_index("posting_id").loc["unknown", "opportunity_status"], "needs_review")

    def test_empty_search_batch_keeps_coverage_and_classification_headers(self):
        with (
            patch.object(search_pipeline, "extract_search_jobs", return_value=([], {"query_results": []})),
            patch.object(search_pipeline, "initialize_database", return_value=self.database_path),
            patch.object(search_pipeline, "__file__", str(self.root / "search_pipeline.py")),
            patch.object(raw_storage, "__file__", str(self.root / "raw_storage.py")),
        ):
            main.run_pipeline(source="jsearch")
        classifications = pd.read_csv(self.root / "reports/job_classifications.csv")
        self.assertTrue(classifications.empty)
        self.assertIn("opportunity_status", classifications.columns)
        coverage = pd.read_csv(self.root / "reports/collection_coverage.csv")
        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage.iloc[0]["analyzed_posting_count"], 0)


if __name__ == "__main__":
    unittest.main()
