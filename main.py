#!/usr/bin/env python3
"""
main.py — Backup Integrity Verification
========================================
Designed to run *after* a daily backup has been performed.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from config import config
from email_alert import send_alert

# ── helpers ────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)

# ── scanning ───────────────────────────────────────────────────────────────

def scan_backup_dir(backup_dir: str, report_name: str) -> List[Dict[str, Any]]:
    """
    Recursively walk *backup_dir* and return a list of dicts, one per
    file, each containing:

    - ``path``  — relative POSIX path from *backup_dir*
    - ``size``  — size in bytes
    - ``mtime`` — ISO-8601 UTC timestamp of last modification
    - ``btime`` — ISO-8601 UTC timestamp of birth/creation (st_birthtime on macOS/BSD, st_mtime fallback on Linux)

    The report file itself (``report_name``) is excluded from the scan.
    Files that cannot be stat'd (broken symlinks, permission errors) are logged and skipped.
    """
    files: List[Dict[str, Any]] = []
    backup_root = Path(backup_dir)

    for dirpath, _dirnames, filenames in os.walk(backup_dir):
        for fname in filenames:
            full_path = Path(dirpath) / fname
            rel_path = full_path.relative_to(backup_root).as_posix()

            # Skip the report itself.
            if rel_path == report_name:
                continue

            try:
                stat = full_path.stat()
            except (OSError, PermissionError) as exc:
                print(f"[warn] Could not stat '{rel_path}': {exc}")
                continue

            # st_birthtime exists on macOS/BSD but not Linux; fall back to mtime.
            birthtime = getattr(stat, "st_birthtime", None)
            if birthtime is None:
                birthtime = stat.st_mtime

            files.append(
                {
                    "path": rel_path,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                    "btime": datetime.fromtimestamp(
                        birthtime, tz=timezone.utc
                    ).isoformat(),
                }
            )

    return files

def count_total_folders(backup_dir: str) -> int:
    """
    Count the total number of folders (directories) in *backup_dir*.
    """
    total_folders = 0
    for _, dirnames, _ in os.walk(backup_dir):
        total_folders += len(dirnames)
    return total_folders

# ── previous report ───────────────────────────────────────────────────────


def load_previous_report(report_path: str) -> Dict[str, Any] | None:
    """
    Load and return the previous ``backup_report.json``.
    Returns ``None`` when the file doesn't exist or cannot be parsed.
    """
    if not os.path.isfile(report_path):
        return None
    try:
        with open(report_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[warn] Could not load previous report: {exc}")
        return None


def _build_previous_index(
    previous_report: Dict[str, Any] | None,
) -> Dict[str, int]:
    """
    Return a ``{relative_path: size}`` lookup from the previous report's
    ``files`` list.  Returns an empty dict when there is no previous report.
    """
    if previous_report is None:
        return {}

    previous_index: Dict[str, int] = {}
    for entry in previous_report.get("files", []):
        previous_index[entry["path"]] = entry["size"]

    return previous_index


# ── verification ──────────────────────────────────────────────────────────


def verify_backup(
    current_files: List[Dict[str, Any]],
    previous_index: Dict[str, int],
    max_age_hours: float,
    diff_threshold: float,
) -> List[str]:
    """
    Compare *current_files* against the *previous_index* and return a list
    of error strings if any.
    """
    errors: List[str] = []
    now = _now_utc()
    freshness_cutoff = now - timedelta(hours=max_age_hours)

    current_paths: set[str] = set()

    for entry in current_files:
        rel_path = entry["path"]
        current_paths.add(rel_path)
        file_size = entry["size"]
        file_mtime = datetime.fromisoformat(entry["mtime"])
        file_btime = datetime.fromisoformat(entry["btime"])

        # 1. Freshness check
        if file_mtime < freshness_cutoff and file_btime < freshness_cutoff:
            age_h = (now - file_mtime).total_seconds() / 3600
            age_b_h = (now - file_btime).total_seconds() / 3600
            errors.append(
                f"STALE file '{rel_path}': last modified {age_h:.1f} h ago || last created {age_b_h:.1f} h ago "
                f"(threshold: {max_age_hours} h)"
            )

        # 2. Size-drop check (only when a previous reference exists)
        if rel_path in previous_index:
            prev_size = previous_index[rel_path]
            if prev_size > 0 and file_size < diff_threshold * prev_size:
                errors.append(
                    f"SIZE DROP '{rel_path}': {prev_size} → {file_size} bytes "
                )

    # 3. Missing-file check
    for prev_path in previous_index:
        if prev_path not in current_paths:
            errors.append(f"MISSING file '{prev_path}': present in previous backup wasn't found in current backup")

    return errors


# ── report writing ────────────────────────────────────────────────────────


def build_report(
    current_files: List[Dict[str, Any]],
    total_folders: int,
    errors: List[str],
) -> Dict[str, Any]:
    """
    Build the JSON-serialisable report dict.

    * ``backup_status`` is ``"success"`` when *errors* is empty, otherwise
      ``"failure"``.
    * ``summary.errors`` contains the error strings (empty list on success).
    """
    total_size = sum(f["size"] for f in current_files)
    status = "success" if not errors else "failure"

    return {
        "date": _now_utc().isoformat(),
        "backup_status": status,
        "files": [
            {"path": f["path"], "size": f["size"]} for f in current_files
        ],
        "summary": {
            "total_folders": total_folders,
            "total_files": len(current_files),
            "total_size": total_size,
            "errors": errors,
        },
    }


def save_report(report: Dict[str, Any], report_path: str) -> None:
    """Write *report* as pretty-printed JSON to *report_path*."""
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=4, ensure_ascii=False)
    print(f"[info] Report written to {report_path}")


# ── main entry point ──────────────────────────────────────────────────────


def main() -> None:
    backup_dir = config.backup_dir
    report_path = os.path.join(backup_dir, config.report_name)

    # --- pre-flight checks --------------------------------------------------
    if not os.path.isdir(backup_dir):
        print(f"[error] Backup directory does not exist: {backup_dir}")
        sys.exit(1)

    # --- load previous report ------------------------------------------------
    previous_report = load_previous_report(report_path)
    is_first_run = previous_report is None
    if is_first_run:
        print("[info] No previous backup_report.json found — first run.")
    else:
        prev_date = previous_report.get("date", "unknown")
        print(f"[info] Previous report dated {prev_date} loaded.")

    previous_index = _build_previous_index(previous_report)

    # --- scan current backup -------------------------------------------------
    print(f"[info] Scanning {backup_dir} …")
    current_files = scan_backup_dir(backup_dir, config.report_name)
    total_folders = count_total_folders(backup_dir)
    print(
        f"[info] Found {len(current_files)} file(s) in "
        f"{total_folders} folder(s)."
    )

    # --- verify integrity ----------------------------------------------------
    errors = verify_backup(
        current_files,
        previous_index,
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

    # --- write new report (always) -------------------------------------------
    report = build_report(current_files, total_folders, errors)
    save_report(report, report_path)

    # --- exit code -----------------------------------------------------------
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
