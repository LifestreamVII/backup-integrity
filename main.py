#!/usr/bin/env python3
"""
main.py — Backup Integrity Verification
========================================
Designed to run *after* a daily backup has been performed.
"""

import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from config import config
from email_alert import send_alert
import db

# ── helpers ────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)

def _short_hash(text: str) -> str:
    """Deterministic 8-char hex hash of arbitrary text."""
    return hashlib.sha256(text.encode()).hexdigest()[:8]

# ── scanning ───────────────────────────────────────────────────────────────

def scan_backup_dir(conn: sqlite3.Connection, backup_dir: str) -> int:
    """
    Recursively walk *backup_dir* and stream file metadata into the
    *manifest* table.  Returns the total number of folders encountered.
    """
    backup_root = Path(backup_dir)
    total_folders = 0

    # Explicit transaction — commit once at the end instead of once per file.
    conn.execute("BEGIN")
    for dirpath, dirnames, filenames in os.walk(backup_dir):
        total_folders += 1  # count this directory (os.walk yields one row per dir)
        for fname in filenames:
            full_path = Path(dirpath) / fname
            rel_path = full_path.relative_to(backup_root).as_posix()

            try:
                stat = full_path.stat()
            except (OSError, PermissionError) as exc:
                print(f"[warn] Could not stat '{rel_path}': {exc}")
                continue

            # st_birthtime exists on macOS/BSD but not Linux; fall back to mtime.
            birthtime = getattr(stat, "st_birthtime", None)
            if birthtime is None:
                birthtime = stat.st_mtime
            try:
                db.save(conn, "manifest",
                {
                        "path": rel_path,
                        "size": stat.st_size,
                        "mtime": datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                        "btime": datetime.fromtimestamp(
                            birthtime, tz=timezone.utc
                        ).isoformat(),
                }, commit=False)
            except sqlite3.Error as exc:
                print(f"[warn] Could not save metadata for '{rel_path}': {exc}")

    conn.commit()
    return total_folders

# ── previous report ───────────────────────────────────────────────────────

def load_previous_meta(conn: sqlite3.Connection, bdir_id: str):
    """
    Load and return the previous metadata for the given backup directory ID.
    Returns ``None`` when the metadata doesn't exist or cannot be parsed.
    """
    try:
        result = db.read_meta(conn, bdir_id)
        return result if result else None
    except OSError as exc:
        print(f"[warn] Could not load previous report: {exc}")
        return None


# ── verification ──────────────────────────────────────────────────────────


def verify_backup(
    conn: sqlite3.Connection,
    max_age_hours: float,
    diff_threshold: float,
) -> List[str]:
    """
    Compare current manifest against the previous snapshot and return a list
    of error strings (empty when everything is healthy).

    Every comparison is done via streaming SQL queries — no in-memory index
    of the previous dataset is built, so the verification scales to millions
    of files without a proportional memory footprint.
    """
    errors: List[str] = []
    now = _now_utc()
    freshness_cutoff = now - timedelta(hours=max_age_hours)
    cutoff_iso = freshness_cutoff.isoformat()

    # ── 1. Freshness check (streaming) ────────────────────────────────────────────
    # Files whose mtime AND btime are both older than the threshold.
    cur = conn.execute(
        "SELECT path, mtime, btime FROM manifest "
        "WHERE mtime < ? AND btime < ?",
        (cutoff_iso, cutoff_iso),
    )
    stale_count = 0
    for rel_path, mtime_str, btime_str in cur:
        stale_count += 1
        if stale_count <= 10:  # cap individual error lines to avoid flooding
            age_h = (now - datetime.fromisoformat(mtime_str)).total_seconds() / 3600
            age_b_h = (now - datetime.fromisoformat(btime_str)).total_seconds() / 3600
            errors.append(
                f"STALE file '{rel_path}': last modified {age_h:.1f} h ago "
                f"|| last created {age_b_h:.1f} h ago "
                f"(threshold: {max_age_hours} h)"
            )
    if stale_count > 10:
        errors.append(
            f"… and {stale_count - 10} more stale file(s) (of {stale_count} total)"
        )

    # ── 2. Size-drop check (streaming JOIN) ──────────────────────────────────
    # Files that still exist but have shrunk significantly since last scan.
    cur = conn.execute(
        "SELECT m.path, m.size, p.size "
        "FROM manifest m "
        "JOIN previous p ON m.path = p.path "
        "WHERE m.size < p.size * ?",
        (1 - diff_threshold,),
    )
    for rel_path, new_size, old_size in cur:
        errors.append(
            f"SIZE DROP '{rel_path}': {old_size} → {new_size} bytes "
            f"({new_size / old_size:.0%} of previous, threshold: {diff_threshold:.0%})"
        )

    # ── 3. Missing-file check (streaming LEFT JOIN) ─────────────────────────
    # Files from the previous scan that no longer exist in the current one.
    cur = conn.execute(
        "SELECT p.path FROM previous p "
        "LEFT JOIN manifest m ON m.path = p.path "
        "WHERE m.path IS NULL"
    )
    for (rel_path,) in cur:
        errors.append(
            f"MISSING file '{rel_path}': present in previous run but absent now"
        )

    return errors


# ── report writing ────────────────────────────────────────────────────────

def save_report(
    conn: sqlite3.Connection,
    bdir_id: str,
    total_folders: int,
    errors: List[str],
) -> None:
    """
    Persist the run results into the *meta* table and rotate the current
    *manifest* into the *previous* table for next run's comparison.
    """
    total_files = db.count_manifest(conn)
    total_size = db.sum_manifest_size(conn)
    status = "success" if not errors else "failure"

    db.save_meta(
        conn,
        bdir_id=bdir_id,
        date=_now_utc().isoformat(),
        status=status,
        total_folders=total_folders,
        total_files=total_files,
        total_size=total_size,
        errors=errors if errors else None,
    )

    # Snapshot current manifest → previous for next run.
    db.rotate_previous(conn)

    print(f"[info] Report saved to database (status={status}, files={total_files}, size={total_size}).")


# ── main entry point ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backup Integrity Verification: scan backup directory and compare against baseline."
    )
    parser.add_argument(
        "--update-bad-baseline",
        action="store_true",
        help="Update the baseline report even when errors are found (not recommended for production use)",
    )
    args = parser.parse_args()

    backup_dir = config.backup_dir
    abs_backup_dir = os.path.abspath(backup_dir)
    bdir_id = _short_hash(abs_backup_dir)

    state_dir = config.state_dir
    db_path = os.path.join(state_dir, config.db_name)
    db.init_db(db_path)
    conn = db.connect_db(db_path)

    # --- pre-flight checks --------------------------------------------------
    if not os.path.isdir(backup_dir):
        print(f"[error] Backup directory does not exist: {backup_dir}")
        sys.exit(1)

    if not os.path.isdir(state_dir):
        print(f"[info] State directory does not exist, creating: {state_dir}")
        os.makedirs(state_dir, exist_ok=True)

    # --- load previous report ------------------------------------------------
    previous_meta = load_previous_meta(conn, bdir_id)
    is_first_run = previous_meta is None
    if is_first_run:
        print("[info] No previous report found — this is the first run.")
    else:
        prev_date = previous_meta.get("date", "unknown")
        print(f"[info] Previous report dated {prev_date} loaded.")

    # --- scan current backup -------------------------------------------------
    print(f"[info] Scanning {backup_dir} …")
    db.clear_manifest(conn)
    total_folders = scan_backup_dir(conn, backup_dir)

    # --- verify integrity ----------------------------------------------------
    errors = verify_backup(
        conn=conn,
        max_age_hours=config.max_age_hours,
        diff_threshold=config.diff_threshold,
    )

    if errors:
        print(f"[warn] {len(errors)} problem(s) detected:")
        for err in errors:
            print(f"  ✗ {err}")
        send_alert(errors)
    else:
        print("[info] All checks passed — backup is healthy.")

    # --- write new report ----------------------------------------------------
    # By default, only update baseline on successful runs.
    # Use --update-bad-baseline to force update even when errors are found.
    if errors and not args.update_bad_baseline:
        print("[info] Baseline NOT updated (errors found and --update-bad-baseline not set).")
        print(f"[info] To force baseline update despite errors, run with --update-bad-baseline")
    else:
        save_report(conn, bdir_id, total_folders, errors)
        if errors:
            print("[warn] Baseline updated despite errors (--update-bad-baseline was set).")

    # --- cleanup -------------------------------------------------------------
    db.close_db(conn)

    # --- exit code -----------------------------------------------------------
    sys.exit(1 if errors else 0)

if __name__ == "__main__":
    main()