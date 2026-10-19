import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from config import GREENHOUSE_BOARDS
from opportunity_rules import CANDIDATE_STATUSES, classify_opportunities
from skill_analysis import (
    extract_skills,
    html_to_text,
    read_latest_jobs,
)


def generate_reports(
    database_path: Path,
    output_dir: Path,
    board_tokens: tuple[str, ...] | None = None,
    *, source: str = "greenhouse", candidate_only: bool = False,
) -> tuple[Path, Path, Path]:
    """Export technology mentions from the latest collection per board.

    Args:
        database_path: SQLite database containing processed postings.
        output_dir: Directory for the latest CSV report and PNG chart.
        board_tokens: Board/query scopes for the selected provider.
        source: greenhouse or jsearch; sources are never silently combined.
        candidate_only: Limit the chart to explicit student/entry-level candidates.

    Returns:
        Paths to the technology CSV, chart and collection-coverage CSV.
        Existing reports at these paths are refreshed on each run.
    """
    collections, all_jobs = read_latest_jobs(
        database_path, board_tokens=board_tokens, source=source,
    )
    all_jobs = classify_opportunities(all_jobs)
    jobs_df = all_jobs.loc[all_jobs["role_match_status"].eq("matched")].copy()
    if candidate_only:
        jobs_df = jobs_df.loc[jobs_df["opportunity_status"].isin(CANDIDATE_STATUSES)].copy()
    posting_label = "student/entry-level candidates" if candidate_only else "title-matched postings"

    descriptions = jobs_df["description_html"].map(html_to_text)
    skills = descriptions.map(extract_skills)
    total_postings = len(jobs_df)
    empty_descriptions = int(descriptions.eq("").sum())

    counts = skills.explode().dropna().value_counts()
    report = counts.rename_axis("technology").reset_index(
        name="posting_count"
    )

    if total_postings:
        report["posting_share_pct"] = (
            report["posting_count"] / total_postings * 100
        ).round(1)
    else:
        report["posting_share_pct"] = 0.0

    report = report.sort_values(
        ["posting_count", "technology"],
        ascending=[False, True],
    ).reset_index(drop=True)

    snapshot_times = [
        datetime.fromisoformat(value).astimezone(timezone.utc)
        for value in collections["snapshot_saved_at_utc"]
    ]
    earliest_snapshot = min(snapshot_times)
    latest_snapshot = max(snapshot_times)

    # Board tokens and collection IDs have the same order in the CSV.
    report["source"] = source
    report["posting_scope"] = "entry_level_candidates" if candidate_only else "all_seniority"
    report["board_tokens"] = ", ".join(collections["board_token"])
    report["collection_ids"] = ", ".join(
        str(value) for value in collections["collection_id"]
    )
    report["snapshot_time_min_utc"] = earliest_snapshot.isoformat()
    report["snapshot_time_max_utc"] = latest_snapshot.isoformat()
    report["monitored_scope_count"] = len(collections)
    if source == "greenhouse":
        report["monitored_board_count"] = len(collections)
        report["contributing_board_count"] = jobs_df["board_token"].nunique()
    report["employer_count"] = jobs_df["company"].nunique()
    report["analyzed_posting_count"] = total_postings
    report["empty_description_count"] = empty_descriptions

    # Retain source coverage even when a board has no matched postings.
    coverage = collections.copy()
    coverage.insert(
        0, "company",
        coverage["board_token"].map(
            lambda token: GREENHOUSE_BOARDS.get(token, token) if source == "greenhouse" else "JSearch student searches"
        ),
    )
    empty_counts = (
        jobs_df.assign(description_empty=descriptions.eq(""))
        .groupby("board_token")["description_empty"]
        .sum()
    )
    coverage["empty_description_count"] = (
        coverage["board_token"].map(empty_counts).fillna(0).astype(int)
    )

    candidate_counts = all_jobs.loc[
        all_jobs["opportunity_status"].isin(CANDIDATE_STATUSES)
    ].groupby("board_token").size()
    analyzed_counts = jobs_df.groupby("board_token").size()
    coverage["candidate_posting_count"] = coverage["board_token"].map(candidate_counts).fillna(0).astype(int)
    coverage["analyzed_posting_count"] = coverage["board_token"].map(analyzed_counts).fillna(0).astype(int)
    coverage["posting_scope"] = "entry_level_candidates" if candidate_only else "all_seniority"

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "technology_mentions.csv"
    chart_path = output_dir / "technology_mentions.png"
    coverage_path = output_dir / "collection_coverage.csv"

    report.to_csv(csv_path, index=False, encoding="utf-8-sig")
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig")
    classifications = all_jobs.drop(columns=["description_html"]).copy()
    classifications["skills"] = all_jobs["description_html"].map(html_to_text).map(extract_skills).map(", ".join)
    classifications.to_csv(output_dir / "job_classifications.csv", index=False, encoding="utf-8-sig")

    chart_data = report.iloc[::-1]
    height = max(5.0, 0.35 * len(chart_data) + 2.4)
    fig, ax = plt.subplots(figsize=(10.5, height))
    fig.subplots_adjust(left=0.20, right=0.95, bottom=0.17, top=0.80)

    company_labels = ", ".join(coverage["company"])
    collection_label = (
        f"Latest collection per board | {len(collections)} boards monitored"
        if source == "greenhouse"
        else "Latest JSearch query batch | One page per query | Limited search coverage"
    )
    collected_range = (
        f"{earliest_snapshot:%Y-%m-%d %H:%M} - "
        f"{latest_snapshot:%Y-%m-%d %H:%M} UTC"
    )

    fig.suptitle(
        "Technology mentions in job postings",
        x=0.20, y=0.97, ha="left",
        fontsize=17, fontweight="bold", color="#172B4D",
    )
    fig.text(
        0.20, 0.91,
        f"{company_labels} | Israel | {total_postings} {posting_label}\n"
        f"{collection_label} | "
        f"Descriptions: {total_postings - empty_descriptions}/{total_postings}\n"
        f"Snapshot range: {collected_range}",
        ha="left", va="top", fontsize=9, color="#526174",
    )

    if chart_data.empty:
        message = (
            "No postings match the selected report scope in the latest collections."
            if total_postings == 0
            else "No configured technologies detected."
        )
        ax.text(
            0.5, 0.5, message,
            ha="center", va="center", transform=ax.transAxes,
        )
        ax.set_axis_off()
    else:
        bars = ax.barh(
            chart_data["technology"],
            chart_data["posting_count"],
            color="#2563EB",
            height=0.68,
        )
        labels = [
            f"{row.posting_count} ({row.posting_share_pct:.1f}%)"
            for row in chart_data.itertuples()
        ]
        ax.bar_label(bars, labels=labels, padding=5, fontsize=9)

        ax.set_xlim(0, chart_data["posting_count"].max() * 1.35)
        ax.set_xlabel("Number of postings mentioning the technology")
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis="x", color="#E2E8F0", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", length=0, labelsize=10)

        for side in ["top", "right", "left"]:
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color("#CBD5E1")

    fig.text(
        0.20, 0.04,
        "Each technology is counted once per posting. Technologies can overlap.\n"
        + ("Candidate labels require human review; search results do not cover the entire market."
           if candidate_only else "Mentions from monitored boards; all seniority levels included."),
        fontsize=8.5, color="#526174",
    )

    try:
        fig.savefig(chart_path, dpi=180, bbox_inches="tight")
    finally:
        plt.close(fig)

    return csv_path, chart_path, coverage_path


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent
    source = os.environ.get("JOB_SOURCE", "greenhouse").strip().lower()
    csv_path, chart_path, coverage_path = generate_reports(
        database_path=project_dir / "data" / "job_market.sqlite3",
        output_dir=project_dir / "reports", source=source,
        candidate_only=source == "jsearch",
    )

    print(f"CSV report saved: {csv_path}")
    print(f"Chart saved: {chart_path}")
    print(f"Collection coverage saved: {coverage_path}")
