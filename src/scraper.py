"""
Indian Express scraper.

Strategy:
  1. Try RSS feeds first (no auth needed) to get article list per section.
  2. For each article, fetch the full HTML using session cookies (your IE login).
  3. Parse with BeautifulSoup. IE's article body is in <div class="full-details"> or
     <div id="pcl-full-content">. Layout shifts occasionally; we fall back to <article>.

Honest caveats:
  - IE's HTML structure changes a few times a year. When it breaks, fix `_extract_article_body`.
  - Cookies typically last 2-4 weeks before IE invalidates them. Refresh from browser.
  - We dedupe by URL. Some articles cross-post in multiple sections.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

# RSS feeds for the sections most relevant to UPSC.
# Source: https://indianexpress.com/syndication/
SECTION_FEEDS: dict[str, str] = {
    "Editorial": "https://indianexpress.com/section/opinion/editorials/feed/",
    "Op-Ed": "https://indianexpress.com/section/opinion/columns/feed/",
    "Explained": "https://indianexpress.com/section/explained/feed/",
    "Front Page": "https://indianexpress.com/print/front-page/feed/",
    "India": "https://indianexpress.com/section/india/feed/",
    "Economy": "https://indianexpress.com/section/business/economy/feed/",
    "World": "https://indianexpress.com/section/world/feed/",
    "Science": "https://indianexpress.com/section/technology/science/feed/",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class Article:
    title: str
    url: str
    section: str
    published: datetime | None = None
    summary: str = ""  # RSS-provided summary
    content: str = ""  # full body text
    word_count: int = 0
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "section": self.section,
            "published": self.published.isoformat() if self.published else None,
            "summary": self.summary,
            "content": self.content,
            "word_count": self.word_count,
        }


def _build_session(cookies_json: str | None) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }
    )
    if cookies_json:
        try:
            cookies = json.loads(cookies_json)
            for c in cookies:
                # Cookie-Editor / EditThisCookie format
                s.cookies.set(
                    name=c["name"],
                    value=c["value"],
                    domain=c.get("domain", ".indianexpress.com"),
                    path=c.get("path", "/"),
                )
            log.info("Loaded %d cookies into session", len(cookies))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log.warning("Failed to parse IE_COOKIES_JSON: %s", e)
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _fetch(session: requests.Session, url: str) -> str:
    r = session.get(url, timeout=20)
    r.raise_for_status()
    return r.text


def _is_today(published: datetime | None, today_local: datetime) -> bool:
    if not published:
        return True  # be permissive if RSS didn't provide a date
    # IE timestamps are in IST. Compare on local date.
    pub_local = published.astimezone(today_local.tzinfo)
    return pub_local.date() == today_local.date()


def _parse_feed(section: str, feed_url: str, today_local: datetime, max_items: int) -> list[Article]:
    parsed = feedparser.parse(feed_url)
    articles: list[Article] = []
    for entry in parsed.entries[: max_items * 2]:  # over-fetch; we'll filter by date
        try:
            pub = dateparser.parse(entry.get("published") or entry.get("updated") or "")
        except (ValueError, TypeError):
            pub = None
        if pub and pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if not _is_today(pub, today_local):
            continue
        articles.append(
            Article(
                title=BeautifulSoup(entry.title, "lxml").get_text(strip=True),
                url=entry.link,
                section=section,
                published=pub,
                summary=BeautifulSoup(entry.get("summary", ""), "lxml").get_text(" ", strip=True),
            )
        )
        if len(articles) >= max_items:
            break
    log.info("Section %-12s: %d articles from feed", section, len(articles))
    return articles


def _extract_article_body(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    # Remove obvious junk before extraction
    for tag in soup.select(
        "script, style, noscript, iframe, .ev-meter-content, .adunit, .also-read, "
        ".storytags, .related-widget, .premium-box, .ie-explained-box, .author-box, "
        ".social-share-block, .newsletter-form, figure"
    ):
        tag.decompose()

    candidates = [
        "div#pcl-full-content",
        "div.full-details",
        "div.story_details",
        "div.articles div.full-details",
        "article",
    ]
    for sel in candidates:
        node = soup.select_one(sel)
        if node:
            text = node.get_text("\n", strip=True)
            if len(text) > 400:  # body must be substantive
                return _clean_text(text)
    # Last-ditch: largest <p>-block on the page
    paras = soup.find_all("p")
    if paras:
        return _clean_text("\n".join(p.get_text(" ", strip=True) for p in paras))
    return ""


def _clean_text(text: str) -> str:
    # Collapse whitespace and strip IE's "ALSO READ" / paywall lines
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = re.sub(r"^(ALSO READ|MUST READ|READ MORE).*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r"Subscribe to.*?Express Premium", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def hydrate_article(session: requests.Session, art: Article) -> Article:
    """Fetch full body for a single article. Mutates and returns."""
    try:
        html = _fetch(session, art.url)
    except Exception as e:
        log.warning("fetch failed for %s: %s", art.url, e)
        return art
    body = _extract_article_body(html)
    art.content = body
    art.word_count = len(body.split())
    return art


def fetch_todays_articles(
    today_local: datetime,
    *,
    cookies_json: str | None = None,
    max_per_section: int = 15,
    sections: Iterable[str] | None = None,
) -> list[Article]:
    session = _build_session(cookies_json)
    sections_to_use = list(sections) if sections else list(SECTION_FEEDS.keys())

    seen: set[str] = set()
    all_articles: list[Article] = []
    for section in sections_to_use:
        feed_url = SECTION_FEEDS.get(section)
        if not feed_url:
            log.warning("Unknown section %s", section)
            continue
        try:
            arts = _parse_feed(section, feed_url, today_local, max_per_section)
        except Exception as e:
            log.warning("feed %s failed: %s", section, e)
            continue
        for a in arts:
            if a.url in seen:
                continue
            seen.add(a.url)
            all_articles.append(a)

    log.info("Hydrating %d unique articles", len(all_articles))
    for a in all_articles:
        hydrate_article(session, a)
    # Filter out anything where body extraction failed badly
    good = [a for a in all_articles if a.word_count >= 120]
    log.info("Kept %d/%d articles after body-length filter", len(good), len(all_articles))
    return good


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from zoneinfo import ZoneInfo

    cookies = os.environ.get("IE_COOKIES_JSON")
    today = datetime.now(ZoneInfo(os.environ.get("TIMEZONE", "Asia/Kolkata")))
    arts = fetch_todays_articles(today, cookies_json=cookies, max_per_section=5)
    for a in arts:
        print(f"[{a.section}] {a.title} ({a.word_count} words) — {a.url}")
