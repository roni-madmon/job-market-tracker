"""Explainable student/entry-level hints, not eligibility guarantees."""

import re

import pandas as pd

from skill_analysis import html_to_text


RULE_VERSION = "opportunity-v1"
CANDIDATE_STATUSES = {"student_candidate", "junior_candidate", "entry_level_candidate"}
STUDENT_TITLE = re.compile(r"\b(?:student|intern|internship)\b|סטודנט", re.I)
JUNIOR_TITLE = re.compile(r"\b(?:junior|graduate|entry[\s-]+level)\b|ג[׳']?וניור", re.I)
STUDENT_DESCRIPTION = re.compile(
    r"\bcurrently\s+(?:enrolled|pursuing)\b|\b(?:student|internship)\s+(?:position|role)\b",
    re.I,
)
NO_EXPERIENCE = re.compile(
    r"\bno\s+(?:(?:prior|previous|professional|work)\s+)*experience\s+(?:is\s+)?required\b"
    r"|ללא\s+ניסיון", re.I,
)
YEARS = re.compile(
    r"\b(?P<minimum>\d{1,2})(?:\s*[-–—]\s*\d{1,2})?\s*\+?\s*"
    r"(?:years?|yrs?)\s+(?:of\s+)?(?:(?:relevant|professional|work|hands-on)\s+)*experience\b",
    re.I,
)
REQUIRED_HEADING = re.compile(
    r"^(?:requirements|qualifications|what (?:you(?:'ll| will) need|you bring|we look for)"
    r"|must.have|דרישות)(?:\s*[:：].*)?$", re.I,
)
PREFERRED = re.compile(r"\b(?:preferred|nice.to.have|bonus|advantage)\b|יתרון", re.I)
PREFERRED_HEADING = re.compile(
    r"^(?:preferred(?: qualifications| skills)?|nice.to.have|bonus(?: points)?|יתרון)\s*[:：]?$",
    re.I,
)


def _experience_evidence(description: str) -> tuple[int | None, list[str], bool]:
    """Read explicit experience phrases; keep alternatives for manual review.

    This is deliberately a limited English rule set. Unsupported wording
    remains unknown. A missing match is never interpreted as zero years.
    """
    if not isinstance(description, str):
        return None, [], False
    blocks = re.sub(r"</(?:p|li|div|h[1-6])\s*>|<br\s*/?>", "\n", description, flags=re.I)
    numbers, evidence = [], []
    preferred_section = False
    required_section = False
    ambiguous = False
    for raw_line in blocks.splitlines():
        line = html_to_text(raw_line).strip(" •-*\t")
        if not line:
            continue
        if REQUIRED_HEADING.search(line):
            preferred_section = False
            required_section = True
        if PREFERRED_HEADING.search(line):
            preferred_section = True
            continue
        if preferred_section:
            continue
        for clause in re.split(r";|[.!?](?:\s|$)", line):
            matches = list(YEARS.finditer(clause))
            if not matches:
                continue
            if PREFERRED.search(clause):
                if re.search(r"\b(?:required|must|minimum|at least)\b", clause, re.I):
                    ambiguous = True
                else:
                    continue
            # Avoid treating company history as a candidate requirement.
            requirement_like = required_section or re.search(
                r"\b(?:required|must|minimum|at least|you have|you bring)\b", clause, re.I,
            ) or re.match(r"\s*\d", clause)
            if not requirement_like:
                continue
            numbers.extend(int(match.group("minimum")) for match in matches)
            evidence.append(clause.strip()[:350])
            if re.search(r"\bor\b|equivalent", clause, re.I):
                ambiguous = True
    return (max(numbers) if numbers else None), evidence, ambiguous


def classify_opportunities(jobs: pd.DataFrame) -> pd.DataFrame:
    """Add auditable opportunity labels to already role-classified postings.

    Candidate labels flag postings for human review. Required experience
    above two years or explicit senior titles prevent automatic inclusion
    in the student/entry-level report. Conflicting signals need review.
    """
    result = jobs.copy()
    decisions = []
    for job in result.to_dict(orient="records"):
        title = str(job.get("job_title") or "")
        description = job.get("description_html")
        text = html_to_text(description)
        years, evidence, ambiguous = _experience_evidence(description)
        student_description = STUDENT_DESCRIPTION.search(text)
        no_experience_match = NO_EXPERIENCE.search(text)
        student = bool(STUDENT_TITLE.search(title) or student_description)
        junior = bool(JUNIOR_TITLE.search(title))
        no_experience = bool(no_experience_match)
        for signal in (student_description, no_experience_match):
            if signal:
                evidence.append(text[max(0, signal.start() - 40):signal.end() + 80])
        senior = job.get("seniority_hint") == "senior_or_lead"
        role_status = job.get("role_match_status")
        if role_status == "not_matched":
            status, reason = "out_of_scope", "No configured role-family match."
        elif role_status != "matched":
            status, reason = "needs_review", "Role relevance requires review."
        elif ambiguous:
            status, reason = "needs_review", "Experience alternatives require review."
        elif (senior or (years is not None and years > 2)) and (student or junior or no_experience):
            status, reason = "needs_review", "Entry-level and experienced signals conflict."
        elif senior or (years is not None and years > 2):
            status, reason = "experienced", "Senior title or explicit requirement above two years."
        elif student:
            status, reason = "student_candidate", "Explicit student/intern signal."
        elif junior:
            status, reason = "junior_candidate", "Explicit junior/graduate title."
        elif no_experience or (years is not None and years <= 2):
            status, reason = "entry_level_candidate", "Explicit no-experience or 0-2-year requirement."
        else:
            status, reason = "needs_review", "Seniority/experience is not established by these rules."
        decisions.append({
            "opportunity_status": status,
            "required_experience_years": years,
            "classification_reason": reason,
            "classification_evidence": " | ".join([title, *evidence]),
            "classification_rule_version": RULE_VERSION,
        })
    columns = [
        "opportunity_status", "required_experience_years", "classification_reason",
        "classification_evidence", "classification_rule_version",
    ]
    decision_frame = pd.DataFrame(decisions, columns=columns, index=result.index)
    for column in columns:
        result[column] = decision_frame[column]
    result["required_experience_years"] = result["required_experience_years"].astype("Int64")
    return result
