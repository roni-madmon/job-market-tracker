import sqlite3
from contextlib import closing
from pathlib import Path


def initialize_database() -> Path:
    """Initialize the SQLite database using the project schema.

    Returns:
        Path to the initialized database.

    Raises:
        OSError: If the schema or database directory cannot be accessed.
        sqlite3.DatabaseError: If database initialization fails.
    """
    project_dir = Path(__file__).resolve().parent
    data_dir = project_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    database_path = data_dir / "job_market.sqlite3"
    schema_path = project_dir / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8-sig")

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(schema_sql)

    return database_path


if __name__ == "__main__":
    database_path = initialize_database()
    print(f"Database ready: {database_path}")

    with closing(sqlite3.connect(database_path)) as connection:
        counts = connection.execute(
            """
            SELECT 'collection_runs', COUNT(*)
            FROM collection_runs

            UNION ALL

            SELECT 'job_snapshots', COUNT(*)
            FROM job_snapshots
            """
        ).fetchall()

    for table_name, row_count in counts:
        print(f"{table_name}: {row_count} rows")