"""
email_alert.py
--------------
Sends an HTML-formatted alert email when the backup integrity check
detects problems.  Uses SMTP with STARTTLS (port 587 by default).
"""

import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from config import config


def _build_html_body(errors: List[str], backup_dir: str) -> str:
    """Return a minimal HTML email body listing every error."""
    rows = "\n".join(f"<li>{err}</li>" for err in errors)
    return f"""\
<html>
<body style="font-family: Arial, sans-serif; color: #333;">
  <h2 style="color: #c0392b;">⚠ Backup Integrity Alert</h2>
  <p><strong>Backup directory:</strong> <code>{backup_dir}</code></p>
  <p><strong>Checked at:</strong> {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
  <p>{len(errors)} problem(s) detected:</p>
  <ul>
    {rows}
  </ul>
  <hr>
  <p style="font-size: 0.85em; color: #888;">
    This alert was generated automatically by the backup-integrity verification script.
  </p>
</body>
</html>"""


def send_alert(errors: List[str], unverified_context: bool = False) -> None:
    """
    Send an email alert listing all *errors* found during the integrity
    check.  Silently returns if SMTP is not configured (empty host).
    """
    if not config.smtp_host:
        print("[email] SMTP not configured — skipping email alert.")
        print("[email] The following errors would have been reported:")
        for err in errors:
            print(f"  • {err}")
        return

    subject = f"{config.email_subject_prefix} {len(errors)} issue(s) detected"
    html = _build_html_body(errors, config.backup_dir)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.email_sender
    msg["To"] = config.email_recipient
    msg.attach(MIMEText(html, "html"))

    if unverified_context:
      context = ssl._create_unverified_context()
    else:
      context = ssl.create_default_context()
    with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
        server.starttls(context=context)
        server.login(config.smtp_user, config.smtp_password)
        server.sendmail(config.email_sender, config.email_recipient, msg.as_string())

    print(f"[email] Alert sent to {config.email_recipient}.")
