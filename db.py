import json
import sqlite3
from typing import Any, Dict, List, Optional

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
            bdir_id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            total_folders INTEGER NOT NULL,
            total_files INTEGER NOT NULL,
            total_size INTEGER NOT NULL,
            skipped TEXT,
            errors TEXT
        );
        """);
        conn.commit()
    except sqlite3.Error as e:
        print(f"[error] Could not initialize database: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def connect_db(db_path: str) -> sqlite3.Connection:
    """Connect to the SQLite database at *db_path*."""
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except sqlite3.Error as e:
        print(f"[error] Could not connect to database: {e}")
        raise

def close_db(conn: sqlite3.Connection) -> None:
    """Close the SQLite database connection."""
    try:
        conn.close()
    except sqlite3.Error as e:
        print(f"[error] Could not close database connection: {e}")

def read(conn: sqlite3.Connection, table: str) -> List[dict]:
    """Read data from the specified table."""
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table};")
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except sqlite3.Error as e:
        print(f"[error] Could not read from {table}: {e}")
        return []

def read_meta(conn: sqlite3.Connection, bdir_id: str) -> Optional[dict]:
    """
    Read the latest metadata row for the given backup directory ID.
    Returns ``None`` when no metadata exists.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM meta WHERE bdir_id = ? ORDER BY date DESC LIMIT 1;",
            (bdir_id,),
        )
        row = cursor.fetchone()
        if row:
            columns = [description[0] for description in cursor.description]
            return dict(zip(columns, row))
        return None
    except sqlite3.Error as e:
        print(f"[error] Could not read metadata from meta: {e}")
        return None

def save(conn: sqlite3.Connection, table: str, data: dict, commit: bool = True) -> None:
    """Insert or replace a single row into *table*.

    Set *commit* to ``False`` when batching many inserts in a caller-managed
    transaction — avoids one fsync per row.
    """
    try:
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        conn.execute(
            f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders});",
            tuple(data.values()),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as e:
        print(f"[error] Could not save data to {table}: {e}")
        raise


def save_meta(
    conn: sqlite3.Connection,
    bdir_id: str,
    date: str,
    status: str,
    total_folders: int,
    total_files: int,
    total_size: int,
    skipped: List[str] | None = None,
    errors: List[str] | None = None,
) -> None:
    """Upsert a row in the *meta* table."""
    save(conn, "meta", {
        "bdir_id": bdir_id,
        "date": date,
        "status": status,
        "total_folders": total_folders,
        "total_files": total_files,
        "total_size": total_size,
        "skipped": json.dumps(skipped or []),
        "errors": json.dumps(errors or []),
    })


def rotate_previous(conn: sqlite3.Connection) -> None:
    """
    Copy the current *manifest* into *previous* (path, size only),
    replacing whatever was there before.
    """
    try:
        conn.execute("DELETE FROM previous;")
        conn.execute(
            "INSERT INTO previous (path, size) "
            "SELECT path, size FROM manifest;"
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"[error] Could not rotate previous: {e}")
        raise


def read_previous(conn: sqlite3.Connection) -> Dict[str, int]:
    """Return ``{path: size}`` from the *previous* table."""
    try:
        cursor = conn.execute("SELECT path, size FROM previous;")
        return {row[0]: row[1] for row in cursor}
    except sqlite3.Error as e:
        print(f"[error] Could not read previous: {e}")
        return {}


def count_manifest(conn: sqlite3.Connection) -> int:
    """Return the number of rows in *manifest*."""
    cursor = conn.execute("SELECT COUNT(*) FROM manifest;")
    return cursor.fetchone()[0]


def sum_manifest_size(conn: sqlite3.Connection) -> int:
    """Return the total size of all files in *manifest*."""
    cursor = conn.execute("SELECT COALESCE(SUM(size), 0) FROM manifest;")
    return cursor.fetchone()[0]


def clear_manifest(conn: sqlite3.Connection) -> None:
    """Delete all rows from *manifest* to prepare for a fresh scan."""
    try:
        conn.execute("DELETE FROM manifest;")
        conn.commit()
    except sqlite3.Error as e:
        print(f"[error] Could not clear manifest: {e}")
        raise