"""
email_alert.py
--------------
Sends an HTML-formatted alert email when the backup integrity check
detects problems.  Uses SMTP with STARTTLS (port 587 by default).
"""

from collections import defaultdict
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import re
import smtplib
import ssl
from typing import List

from config import config

_ERROR_RE = re.compile(r"^(STALE|SIZE DROP|MISSING)(?:\s+file)?\s+'([^']*)':\s*(.*)$")


def _group_and_cap_errors(errors: List[str]) -> dict:
    """Group errors by folder and failure type."""
    # Structure: folder -> type -> list of (path, detail)
    grouped = defaultdict(lambda: defaultdict(list))
    for err in errors:
        m = _ERROR_RE.match(err)
        if m:
            fail_type, path, detail = m.groups()
            folder = Path(path).parent.as_posix()
            if folder == "." or not folder:
                folder = "root"
            grouped[folder][fail_type].append((path, detail))
        else:
            grouped["unknown"]["UNKNOWN"].append(("", err))
    return grouped


def _build_html_body(errors: List[str], backup_dir: str, limit: int = 10) -> str:
    """Return an HTML email body with errors grouped by folder and failure type, and capped."""
    grouped = _group_and_cap_errors(errors)

    sections = []
    for folder, types in sorted(grouped.items()):
        folder_html = f'<div style="margin-bottom: 20px; border-left: 4px solid #c0392b; padding-left: 15px;">'
        folder_html += f'<h3 style="margin: 0 0 10px 0; color: #2c3e50;">📁 Folder: <code>{folder}</code></h3>'

        for fail_type, items in sorted(types.items()):
            type_label = {
                "STALE": "Stale Files",
                "SIZE DROP": "Size Drops",
                "MISSING": "Missing Files",
                "UNKNOWN": "Other Warnings"
            }.get(fail_type, fail_type)

            folder_html += f'<h4 style="margin: 5px 0; color: #e74c3c;">{type_label} ({len(items)} total)</h4>'
            folder_html += '<ul style="margin: 5px 0 10px 0; padding-left: 20px; font-size: 0.9em; font-family: monospace;">'

            for path, detail in items[:limit]:
                if path:
                    folder_html += f"<li><strong>{path}</strong>: {detail}</li>"
                else:
                    folder_html += f"<li>{detail}</li>"

            if len(items) > limit:
                folder_html += f'<li style="color: #7f8c8d; list-style-type: none; font-style: italic;">... and {len(items) - limit} more</li>'

            folder_html += '</ul>'
        folder_html += '</div>'
        sections.append(folder_html)

    grouped_html = "\n".join(sections)

    return f"""\
<html>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.4;">
  <h2 style="color: #c0392b; margin-top: 0;">⚠ Backup Integrity Alert</h2>
  <p><strong>Backup directory:</strong> <code>{backup_dir}</code></p>
  <p><strong>Checked at:</strong> {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
  <p>A total of <strong>{len(errors)}</strong> issues were detected. A preview grouped by folder is shown below. The complete list of errors is attached as a TXT file.</p>
  <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
  {grouped_html}
  <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
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

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = config.email_sender
    msg["To"] = config.email_recipient

    # HTML body
    msg_html = MIMEText(html, "html", "utf-8")
    msg.attach(msg_html)

    # Attach the full report as a text file
    full_report_text = "\n".join(errors)
    attachment = MIMEText(full_report_text, "plain", "utf-8")
    attachment.add_header("Content-Disposition", "attachment", filename="backup_integrity_report.txt")
    msg.attach(attachment)

    if unverified_context:
        context = ssl._create_unverified_context()
    else:
        context = ssl.create_default_context()
    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls(context=context)
            server.login(config.smtp_user, config.smtp_password)
            server.sendmail(config.email_sender, config.email_recipient, msg.as_string())
            print(f"[email] Alert sent to {config.email_recipient}.")
    except Exception as e:
        print("[error] 📧 ❌ Failed to send summary email.")
        print(f"[error] Connection to SMTP server failed: {e}")

