import json
from pathlib import Path

import pandas as pd


def transform_jobs(snapshot: dict) -> pd.DataFrame:
    """Convert a raw snapshot into a structured job-postings table.

    Args:
        snapshot: Saved postings and their collection metadata.

    Returns:
        A DataFrame with standardized columns and source metadata.

    Raises:
        ValueError: If the record count or required columns are invalid.
    """
    if snapshot["source"] == "jsearch":
        return transform_search_jobs(snapshot)
    if snapshot["source"] != "greenhouse":
        raise ValueError("Unsupported source in raw snapshot.")
    jobs = snapshot["jobs"]

    if len(jobs) != snapshot["job_count"]:
        raise ValueError("Snapshot job_count does not match its records.")

    df = pd.json_normalize(jobs)

    required_columns = {"id", "title", "absolute_url"}
    missing_columns = required_columns - set(df.columns)

    if jobs and missing_columns:
        raise ValueError(
            f"Missing required columns: {sorted(missing_columns)}"
        )

    column_mapping = {
        "id": "posting_id",
        "title": "job_title",
        "company_name": "company",
        "location.name": "location",
        "absolute_url": "job_url",
        "content": "description_html",
        "updated_at": "source_updated_at",
        "first_published": "source_first_published_at",
    }

    df = df.reindex(columns=list(column_mapping))
    df = df.rename(columns=column_mapping)

    for column in ["job_title", "company", "location"]:
        df[column] = df[column].astype("string").str.strip()

    df["source"] = snapshot["source"]
    df["board_token"] = snapshot["board_token"]
    df["snapshot_saved_at_utc"] = snapshot["saved_at_utc"]

    return df


def transform_search_jobs(snapshot: dict) -> pd.DataFrame:
    """Normalize JSearch records without truncating descriptions.

    One posting can match multiple search queries. Deduplicate by provider
    job ID, keeping separate IDs for different positions or locations.
    The original repeated records remain in the raw snapshot.
    """
    jobs = snapshot["jobs"]
    if len(jobs) != snapshot["job_count"]:
        raise ValueError("Snapshot job_count does not match its records.")
    df = pd.json_normalize(jobs)
    required = {"job_id", "job_title"}
    if jobs and (required - set(df.columns)):
        raise ValueError("JSearch records lack job_id or job_title.")
    mapping = {
        "job_id": "posting_id", "job_title": "job_title",
        "employer_name": "company", "job_location": "location",
        "job_apply_link": "job_url", "job_description": "description_html",
        "job_posted_at_datetime_utc": "source_first_published_at",
        "job_country": "source_country_code", "job_city": "source_city",
        "job_google_link": "source_google_link",
    }
    df = df.reindex(columns=list(mapping)).rename(columns=mapping)
    for column in ["posting_id", "job_title", "company", "location", "job_url", "source_country_code"]:
        df[column] = df[column].astype("string").str.strip().replace("", pd.NA)
    df["location"] = df["location"].fillna(df["source_city"]).fillna(df["source_country_code"])
    df["job_url"] = df["job_url"].fillna(df["source_google_link"])
    df["source_updated_at"] = pd.NA
    df["source"] = snapshot["source"]
    df["board_token"] = snapshot["board_token"]
    df["snapshot_saved_at_utc"] = snapshot["saved_at_utc"]
    if df["posting_id"].isna().any():
        raise ValueError("JSearch returned a record without a job ID.")
    return df.drop_duplicates(subset=["posting_id"], keep="first").reset_index(drop=True)

def filter_israel_jobs(df: pd.DataFrame) -> pd.DataFrame:
    """Select postings matching the current Israel location rules.

    Args:
        df: Normalized postings containing a location column.

    Returns:
        A filtered copy with country and location-match metadata.
    """
    country_match = df["location"].str.contains(
        r"\bisrael\b",
        case=False,
        na=False,
    )

    city_match = df["location"].str.contains(
        r"\btel[\s-]+aviv\b",
        case=False,
        na=False,
    )

    country_codes = df.get("source_country_code", pd.Series("", index=df.index))
    country_codes = country_codes.fillna("").astype("string").str.strip().str.upper()
    explicit_israel = country_codes.isin(["IL", "ISRAEL"])
    no_country_code = country_codes.eq("")
    result = df.loc[explicit_israel | (no_country_code & (country_match | city_match))].copy()

    result["country"] = "Israel"
    result["location_match_method"] = "city_name"

    result.loc[
        country_match.loc[result.index],
        "location_match_method",
    ] = "country_name"

    result.loc[explicit_israel.loc[result.index], "location_match_method"] = "country_code"
    return result


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent
    raw_dir = project_dir / "data" / "raw"

    snapshot_files = sorted(raw_dir.glob("similarweb_*.json"))

    if not snapshot_files:
        raise FileNotFoundError("No Similarweb snapshots found.")

    latest_snapshot = snapshot_files[-1]

    with latest_snapshot.open(encoding="utf-8") as file:
        snapshot = json.load(file)

    jobs_df = transform_jobs(snapshot)
    israel_jobs_df = filter_israel_jobs(jobs_df)

    print(f"Input file: {latest_snapshot.name}")
    print(f"All postings: {len(jobs_df)}")
    print(f"Israel postings: {len(israel_jobs_df)}")
    print(f"Unmatched locations: {len(jobs_df) - len(israel_jobs_df)}")

    print("\nLocation match methods:")
    print(
        israel_jobs_df["location_match_method"]
        .value_counts()
        .to_string()
    )

    print("\nIsrael postings:")
    print(
        israel_jobs_df[["job_title", "location"]]
        .to_string(index=False)
    )