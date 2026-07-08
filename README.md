# Backup Integrity Checker

This script scans a backup directory, after a backup has been completed, against a timestamped JSON report of all files from the previous backup, including their size. It checks for stale files based on a specified age threshold (default: 24 hours) and reports any abnormalities, more specifically :

- Files that have either not been modified or created within the specified age threshold.
- Files that are present in the report but missing from the backup directory.
- Files that have a large size dip (default: 50% size reduction) compared to the previous backup.

After scanning, it overwrites the JSON report with the current state of the backup directory (no matter the scan result), so that it can be used for comparison in the next run.

Any abnormalities found during the scan are logged and can be sent via email if SMTP settings are configured.

## Configuration

SMTP settings can be configured in `config.py`, along with parameters for the scanning process, such as the target directory, the maximum age threshold and size dip percentage.

**Important:** The baseline report is stored in `STATE_DIR` (configured in `config.py`), which should be outside the backup directory to prevent the baseline from being wiped if the backup directory is recreated. If `STATE_DIR` is not set, it defaults to the current working directory.

## Run

Default run:

```bash
python main.py
```