BEGIN;

-- One record per saved collection.
CREATE TABLE IF NOT EXISTS collection_runs (
    collection_id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    board_token TEXT NOT NULL,
    snapshot_saved_at_utc TEXT NOT NULL,
    raw_file_name TEXT NOT NULL,

    raw_posting_count INTEGER NOT NULL
        CHECK (raw_posting_count >= 0),

    israel_posting_count INTEGER NOT NULL
        CHECK (
            israel_posting_count >= 0
            AND israel_posting_count <= raw_posting_count
        ),

    last_processed_at_utc TEXT NOT NULL,

    UNIQUE (source, board_token, snapshot_saved_at_utc)
);

-- One posting per collection, including its derived labels.
CREATE TABLE IF NOT EXISTS job_snapshots (
    collection_id INTEGER NOT NULL,
    posting_id TEXT NOT NULL,
    job_title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    job_url TEXT NOT NULL,
    description_html TEXT,
    source_updated_at TEXT,
    source_first_published_at TEXT,
    country TEXT NOT NULL,
    location_match_method TEXT NOT NULL,
    job_family TEXT NOT NULL,

    role_match_status TEXT NOT NULL
        CHECK (
            role_match_status IN (
                'matched',
                'needs_review',
                'not_matched'
            )
        ),

    seniority_hint TEXT NOT NULL,

    PRIMARY KEY (collection_id, posting_id),

    FOREIGN KEY (collection_id)
        REFERENCES collection_runs (collection_id)
);

COMMIT;