# Backup Integrity Checker

This script scans a backup directory, after a backup has been completed, against metadata saved from the previous backup in a lightweight database that tracks the file sizes and their paths. It checks for stale files based on a specified age threshold (default: 24 hours) and reports any abnormalities, more specifically :

- Files that have either not been modified or created within the specified age threshold.
- Files that are present in the previous backup metadata but missing from the backup directory.
- Files that have a large size dip (default: 50% size reduction) compared to the previous backup.

**Baseline update behavior:** By default, the previous backup metadata is only updated when all checks pass, at the end of the scan. This prevents a bad backup from becoming the new normal. However, in case where false-positives occur (e.g., an expected large size difference), it is also possible to set the `--update-bad-baseline` flag to force an update even when errors are found.

**Important:** The verification method used in this script assumes that the backup process updates the file modification or creation timestamps when they are copied over. If the backup process does not update these timestamps, the script may incorrectly flag files as stale. A later revision may rely on a completion marker file to indicate that the backup process has completed successfully, which would require a change in the backup process to create such a marker file.

Any abnormalities found during the scan are logged and can be sent via email if SMTP settings are configured.

## Configuration

SMTP settings can be configured in `config.py`, along with parameters for the scanning process, such as the target directory, the maximum age threshold and size dip percentage.

The database file is stored in `STATE_DIR` (configured in `config.py`), which should be outside the backup directory to prevent the baseline from being wiped if the backup directory is recreated. If `STATE_DIR` is not set, it defaults to the current working directory.

## Run

Default run (baseline only updated on success):

```bash
python main.py
```

Force baseline update even when errors are found:

```bash
python main.py --update-bad-baseline
```
