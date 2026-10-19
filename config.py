"""Explicit collection scopes for company boards and role-based searches."""

GREENHOUSE_BOARDS: dict[str, str] = {
    "similarweb": "Similarweb",
    "forter": "Forter",
    "gongio": "Gong",
}

# One collection combines these queries, removing repeated job IDs later.
JSEARCH_SCOPE = "student_tech_israel_v1"
JSEARCH_QUERIES = (
    "Data Student jobs in Israel",
    "Software Student jobs in Israel",
    "DevOps Student jobs in Israel",
)
