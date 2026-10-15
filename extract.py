import requests
from raw_storage import save_raw_jobs


def extract_jobs(board_token: str = "similarweb") -> list[dict]:
    """Fetch public job postings from a Greenhouse company board.

    Retrieves all postings returned by the board, including their
    full descriptions. Location and role filtering happen later.

    Args:
        board_token: Public board identifier, such as "similarweb".

    Returns:
        list[dict]: Raw job postings returned by the API.

    Raises:
        requests.exceptions.RequestException: If the HTTP request fails.
        ValueError: If the response cannot be decoded as JSON.
        KeyError: If the response does not contain the jobs field.
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

    response = requests.get(
        url,
        params={"content": "true"},
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    return data["jobs"]