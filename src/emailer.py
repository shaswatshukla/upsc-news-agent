"""
Email sender. Uses SMTP — works with Gmail (App Password), Outlook, or any provider.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Template

from classifier import EnrichedArticle

log = logging.getLogger(__name__)


HTML_TEMPLATE = Template(
    r"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1a202c; max-width: 720px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 22px; margin: 0 0 4px; color: #1a365d; }
  .sub { color: #718096; font-size: 13px; margin-bottom: 24px; }
  .card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 16px; margin-bottom: 14px; background: #ffffff; }
  .meta { color: #718096; font-size: 12px; margin-bottom: 6px; }
  .tag { display: inline-block; background: #ebf8ff; color: #2c5282; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-right: 4px; }
  .score { background: #f0fff4; color: #276749; }
  h3 { font-size: 15px; margin: 0 0 6px; }
  h3 a { color: #1a365d; text-decoration: none; }
  h3 a:hover { text-decoration: underline; }
  .summary { font-size: 14px; line-height: 1.5; margin: 6px 0 0; }
  .topics { font-size: 12px; color: #4a5568; margin-top: 6px; }
  .footer { color: #a0aec0; font-size: 11px; margin-top: 32px; border-top: 1px solid #edf2f7; padding-top: 12px; }
</style></head><body>
  <h1>UPSC Daily — Indian Express</h1>
  <div class="sub">{{ date_str }} · {{ count }} relevant articles · detailed notes attached as PDF</div>

  {% for ea in items %}
  <div class="card">
    <div class="meta">
      <span class="tag">{{ ea.classification.primary_paper }}</span>
      <span class="tag">{{ ea.article.section }}</span>
      <span class="tag score">Score {{ ea.classification.relevance_score }}/10</span>
    </div>
    <h3><a href="{{ ea.article.url }}">{{ ea.notes.headline }}</a></h3>
    <div class="summary">{{ ea.notes.one_line_summary }}</div>
    {% if ea.notes.context %}<div class="summary"><b>Context:</b> {{ ea.notes.context }}</div>{% endif %}
    {% if ea.classification.topics %}<div class="topics">Topics: {{ ea.classification.topics | join(", ") }}</div>{% endif %}
  </div>
  {% endfor %}

  <div class="footer">
    Filtered by Gemini using the official UPSC CSE syllabus. Detailed Mains/Prelims notes are in the attached PDF.
    Skipped {{ skipped }} non-relevant articles today.
  </div>
</body></html>"""
)


def _smtp_config() -> dict:
    return {
        "host": os.environ["SMTP_HOST"],
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ["SMTP_USER"],
        "password": os.environ["SMTP_PASSWORD"],
        "to": os.environ["EMAIL_TO"],
    }


def send_digest(
    *,
    kept: list[EnrichedArticle],
    skipped_count: int,
    pdf_path: Path | None,
    date: datetime,
) -> None:
    cfg = _smtp_config()

    html = HTML_TEMPLATE.render(
        date_str=date.strftime("%A, %d %B %Y"),
        count=len(kept),
        skipped=skipped_count,
        items=kept,
    )

    plain_lines = [f"UPSC Daily — {date.strftime('%d %b %Y')}", ""]
    for ea in kept:
        n = ea.notes
        plain_lines.append(f"[{ea.classification.primary_paper}] {n.headline}")
        plain_lines.append(f"  {n.one_line_summary}")
        plain_lines.append(f"  {ea.article.url}")
        plain_lines.append("")
    plain = "\n".join(plain_lines)

    msg = EmailMessage()
    msg["Subject"] = f"UPSC Daily — {date.strftime('%d %b %Y')} ({len(kept)} articles)"
    msg["From"] = cfg["user"]
    msg["To"] = cfg["to"]
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    if pdf_path and pdf_path.exists():
        ctype, _ = mimetypes.guess_type(str(pdf_path))
        maintype, subtype = (ctype or "application/pdf").split("/", 1)
        with open(pdf_path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=pdf_path.name)

    log.info("Sending email to %s via %s:%s", cfg["to"], cfg["host"], cfg["port"])
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.login(cfg["user"], cfg["password"])
        s.send_message(msg)
    log.info("Email sent")
