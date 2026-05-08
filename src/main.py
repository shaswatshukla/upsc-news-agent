"""
Entry point. Pipeline:
  scrape today's IE articles -> classify with Gemini -> filter by relevance ->
  summarize survivors -> render PDF + HTML email -> send.

Run locally: cd src && python main.py  (with .env in the src/ or project root)
Run on GitHub Actions: see .github/workflows/daily.yml
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from scraper import fetch_todays_articles
from classifier import enrich_articles, kept_only
from pdf_generator import build_pdf
from emailer import send_digest


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    load_dotenv()
    setup_logging()
    log = logging.getLogger("main")

    tz = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Kolkata"))
    today = datetime.now(tz)
    log.info("Run date: %s", today.isoformat())

    # 1. Scrape
    cookies = os.environ.get("IE_COOKIES_JSON")
    max_per_section = int(os.environ.get("MAX_ARTICLES_PER_SECTION", "15"))
    articles = fetch_todays_articles(today, cookies_json=cookies, max_per_section=max_per_section)
    if not articles:
        log.warning("No articles scraped — aborting before LLM calls")
        return 2

    # 2 + 3. Classify and summarize
    threshold = int(os.environ.get("RELEVANCE_THRESHOLD", "6"))
    enriched = enrich_articles(articles, relevance_threshold=threshold)
    kept = kept_only(enriched)
    skipped = len(enriched) - len(kept)
    log.info("Kept %d, skipped %d", len(kept), skipped)

    if not kept:
        log.warning("No UPSC-relevant articles today — sending light email anyway")

    # 4. PDF
    out_dir = Path(os.environ.get("OUTPUT_DIR", "out"))
    pdf_path = out_dir / f"upsc-{today:%Y-%m-%d}.pdf"
    if kept:
        build_pdf(kept, today, pdf_path)
    else:
        pdf_path = None

    # 5. Email
    try:
        send_digest(kept=kept, skipped_count=skipped, pdf_path=pdf_path, date=today)
    except Exception as e:
        log.exception("Email send failed: %s", e)
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
