import sqlite3

def init_db(db_path: str) -> None:
    """Initialize the SQLite database at *db_path*."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
        -- for files
        CREATE TABLE IF NOT EXISTS manifest (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime TEXT NOT NULL,
            btime TEXT NOT NULL
        );
        -- for previous report
        CREATE TABLE IF NOT EXISTS previous (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL
        );
        -- for metadata, e.g. last run time, etc.
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """);
        conn.commit()
    except sqlite3.Error as e:
        print(f"[error] Could not initialize database: {e}")
    finally:
        if 'conn' in locals():
            conn.close()