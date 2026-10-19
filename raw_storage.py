import json
from datetime import datetime, timezone
from pathlib import Path

def save_raw_jobs(
    jobs: list[dict], board_token: str, *,
    source: str = "greenhouse", context: dict | None = None,
) -> Path:
    """Save unmodified job postings with collection metadata.

    Args:
        jobs: Job postings returned by the API.
        board_token: Company-board token or a versioned search-scope identifier.
        source: Provider identifier.
        context: Non-secret query provenance for inspecting the raw batch.

    Returns:
        Path to the newly created JSON snapshot.

    Raises:
        OSError: If the directory or file cannot be created.
    """
    saved_at = datetime.now(timezone.utc)

    project_dir = Path(__file__).resolve().parent
    output_dir = project_dir / "data" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = saved_at.strftime("%Y%m%dT%H%M%S_%fZ")
    output_path = output_dir / f"{board_token}_{timestamp}.json"

    snapshot = {
        "source": source,
        "board_token": board_token,
        "saved_at_utc": saved_at.isoformat(),
        "job_count": len(jobs),
        "jobs": jobs,
    }

    if context is not None:
        snapshot["collection_context"] = context

    with output_path.open("x", encoding="utf-8") as file:
        json.dump(snapshot, file, ensure_ascii=False, indent=2)

    return output_path