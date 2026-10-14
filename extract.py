import requests
from raw_storage import save_raw_jobs


def extract_jobs():
    """Fetch public job postings from Similarweb's Greenhouse board.

    Retrieves all postings returned by the board, including their
    full descriptions. Location and role filtering happen later.

    Returns:
        list[dict]: Raw job postings returned by the API.

    Raises:
        requests.exceptions.RequestException: If the HTTP request fails.
        ValueError: If the response cannot be decoded as JSON.
        KeyError: If the response does not contain the jobs field.
    """
    url = "https://boards-api.greenhouse.io/v1/boards/similarweb/jobs"

    response = requests.get(
        url,
        params={"content": "true"},
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()
    return data["jobs"]


if __name__ == "__main__":
    jobs = extract_jobs()
    snapshot_path = save_raw_jobs(jobs, board_token="similarweb")
    print(f"Raw data saved to: {snapshot_path}")

    print(f"Jobs received: {len(jobs)}")

    for job in jobs[:5]:
        location = (job.get("location") or {}).get("name", "Unknown")

        print()
        print(f"Title: {job['title']}")
        print(f"Location: {location}")
        print(f"Link: {job['absolute_url']}")