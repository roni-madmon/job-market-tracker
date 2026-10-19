"""Search multiple employers through JSearch using an environment-held key."""

import logging
import os

import requests

from config import JSEARCH_QUERIES


logger = logging.getLogger(__name__)


def extract_search_jobs() -> tuple[list[dict], dict]:
    """Fetch one page for each configured search, failing on partial results.

    JSEARCH_API_KEY must belong to JSEARCH_PROVIDER (openwebninja or
    rapidapi). Keys are sent in request headers and never in saved data.
    Uses the current /search-v2 endpoint and its data.jobs response envelope.
    Exactly one request is made per query; no automatic paid retries or
    cursor pagination are enabled. Duplicate records remain in the raw snapshot.

    Returns:
        Original job records and non-secret search provenance.

    Raises:
        ValueError: If configuration or the response shape is invalid.
        requests.RequestException: If any search request fails.
    """
    provider = os.environ.get("JSEARCH_PROVIDER", "openwebninja").strip().lower()
    api_key = os.environ.get("JSEARCH_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Set JSEARCH_API_KEY before selecting JOB_SOURCE=jsearch.")
    if provider == "openwebninja":
        url = "https://api.openwebninja.com/jsearch/search-v2"
        headers = {"x-api-key": api_key}
    elif provider == "rapidapi":
        url = "https://jsearch.p.rapidapi.com/search-v2"
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": "jsearch.p.rapidapi.com",
        }
    else:
        raise ValueError("JSEARCH_PROVIDER must be openwebninja or rapidapi.")
    if not JSEARCH_QUERIES or len(set(JSEARCH_QUERIES)) != len(JSEARCH_QUERIES):
        raise ValueError("Configure nonempty, distinct JSearch queries.")

    all_jobs = []
    query_results = []
    for query in JSEARCH_QUERIES:
        logger.info("[jsearch] Searching: %s", query)
        response = requests.get(
            url,
            headers=headers,
            params={
                "query": query,
                "country": "il",
                "language": "en",
                "num_pages": 1,
                "date_posted": "all",
            },
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            message = "The server returned an unsuccessful HTTP response."
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = None
            if isinstance(error_payload, dict):
                error = error_payload.get("error")
                detail = error_payload.get("message")
                if not detail and isinstance(error, dict):
                    detail = error.get("message")
                if isinstance(detail, str) and detail.strip():
                    message = detail
            # Show only the API's error message; never log request headers.
            message = message.replace(api_key, "[REDACTED]")
            message = " ".join(message.split())[:500]
            raise requests.HTTPError(
                f"JSearch HTTP {response.status_code} ({provider}, /search-v2): {message}",
                response=response,
            ) from None
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != "OK":
            raise ValueError("JSearch did not return a successful response.")
        data = payload.get("data")
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
            raise ValueError("JSearch response data.jobs must be a list of job records.")
        logger.info("[jsearch] Query returned %d postings.", len(jobs))
        query_results.append({"query": query, "returned_posting_count": len(jobs)})
        all_jobs.extend(jobs)

    return all_jobs, {
        "provider": provider,
        "endpoint": "/search-v2",
        "country": "il",
        "language": "en",
        "pages_per_query": 1,
        "date_posted": "all",
        "query_results": query_results,
    }
