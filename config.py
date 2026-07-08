# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the root of the backed-up directory on the NAS.
# Every file and folder under this path will be verified.
BACKUP_DIR = ""

# Directory where state files are kept (outside the backup tree).
# The baseline report will be stored here to survive backup directory recreation.
# Defaults to the current working directory if not set.
STATE_DIR = ""

# Name of the JSON report (stored in STATE_DIR, not BACKUP_DIR).
REPORT_NAME = "backup_report.json"

# A file whose size drops below DIFF_THRESHOLD × previous size is flagged.
# 0.5 → tolerate up to a 50 % size reduction before alerting.
DIFF_THRESHOLD = 0.5

# Maximum age (in hours) for a file's mtime to be considered "fresh".
# 24 h matches the daily-backup cadence.
MAX_AGE_HOURS = 24

# ---------------------------------------------------------------------------
# Email / SMTP
# ---------------------------------------------------------------------------
SMTP_HOST = ""              # e.g. "smtp.gmail.com"
SMTP_PORT = 587             # 587 = STARTTLS, 465 = SSL
SMTP_USER = ""              # SMTP login username
SMTP_PASSWORD = ""          # SMTP login password / app-password
EMAIL_SENDER = ""           # From address
EMAIL_RECIPIENT = ""        # To address
EMAIL_SUBJECT_PREFIX = "[Backup-Integrity]"


class Config:
    """Centralised, importable configuration object."""

    def __init__(self):
        self.backup_dir = BACKUP_DIR
        self.state_dir = STATE_DIR if STATE_DIR else "."
        self.report_name = REPORT_NAME
        self.diff_threshold = DIFF_THRESHOLD
        self.max_age_hours = MAX_AGE_HOURS

        self.smtp_host = SMTP_HOST
        self.smtp_port = SMTP_PORT
        self.smtp_user = SMTP_USER
        self.smtp_password = SMTP_PASSWORD
        self.email_sender = EMAIL_SENDER
        self.email_recipient = EMAIL_RECIPIENT
        self.email_subject_prefix = EMAIL_SUBJECT_PREFIX


config = Config()