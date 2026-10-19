import json
from pathlib import Path

import pandas as pd

from transform import filter_israel_jobs, transform_jobs


ROLE_RULES = {
    "data_engineering": r"\bdata\s+engineer(?:ing)?\b",
    "data_science": r"\bdata\s+(?:scientist|science)\b",
    "analytics_bi": (
        r"\b(?:data|product|business)\s+analyst\b"
        r"|\bbusiness\s+analytics\b"
        r"|\bbusiness\s+intelligence\b"
        r"|\bbi\s+(?:analyst|developer|engineer)\b"
        r"|\bdata\s+(?:student|intern)\b"
    ),
    "ai_related_engineering": (
        r"\b(?:ai|ml|machine\s+learning)\s+engineer\b"
        r"|\b(?:backend|software)\s+engineer\b.*\b(?:ai|ml)\b"
    ),
    "devops_cloud": (
        r"\b(?:devops|sre|site[\s-]+reliability)\b"
        r"|\bcloud\s+(?:engineer|developer|student|intern)\b"
    ),
    "software_engineering": (
        r"\b(?:software|backend|front[\s-]*end|full[\s-]*stack)\s+"
        r"(?:engineer(?:ing)?|develop(?:er|ment)|student|intern)\b"
    ),
}
# Broader title signals require review when no role rule matches.
ROLE_REVIEW_PATTERN = (
    r"\b(?:analyst|ai|ml|agents?|agentic)\b"
    r"|\bmachine[\s-]+learning\b"
    r"|\bdata\b"
)
SENIORITY_RULES = {
    "senior_or_lead": (
        r"\b(?:senior|sr|lead|principal|staff|director|head|manager|architect)\b"
        r"|\bteam\s+manager\b"
    ),
    "student_or_intern": r"\b(?:student|intern|internship)\b",
    "junior_or_graduate": r"\b(?:junior|graduate|entry[\s-]+level)\b",
}


def classify_jobs(df: pd.DataFrame) -> pd.DataFrame:
    """Add rule-based role and seniority labels using job titles.

    Args:
        df: Normalized postings containing a job_title column.

    Returns:
        A copy with job_family, role_match_status and seniority_hint.
        The first matching rule in each rule dictionary takes priority.
        Labels are title-based hints requiring description review.
    """
    result = df.copy()
    titles = result["job_title"].fillna("")

    result["job_family"] = "unclassified"
    result["role_match_status"] = "not_matched"

    for family, pattern in ROLE_RULES.items():
        mask = (
            result["role_match_status"].eq("not_matched")
            & titles.str.contains(pattern, case=False, na=False)
        )

        result.loc[mask, "job_family"] = family
        result.loc[mask, "role_match_status"] = "matched"

    review_mask = (
    result["role_match_status"].eq("not_matched")
    & titles.str.contains(
        ROLE_REVIEW_PATTERN,
        case=False,
        na=False,
        )
    )
    result.loc[review_mask, "role_match_status"] = "needs_review"

    result["seniority_hint"] = "not_stated_in_title"

    for level, pattern in SENIORITY_RULES.items():
        mask = (
            result["seniority_hint"].eq("not_stated_in_title")
            & titles.str.contains(pattern, case=False, na=False)
        )
        result.loc[mask, "seniority_hint"] = level

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
    classified_df = classify_jobs(israel_jobs_df)

    matched = classified_df[
        classified_df["role_match_status"].eq("matched")
    ]
    review = classified_df[
        classified_df["role_match_status"].eq("needs_review")
    ]

    print(f"Input file: {latest_snapshot.name}")
    print(f"Israel postings: {len(classified_df)}")
    print(f"Title-rule matches: {len(matched)}")
    print(f"Needs review: {len(review)}")

    print("\nMatched job families:")
    print(matched["job_family"].value_counts().to_string())

    print("\nSeniority hints among matches:")
    print(matched["seniority_hint"].value_counts().to_string())

    print("\nTitles requiring review:")
    print(review["job_title"].to_string(index=False))