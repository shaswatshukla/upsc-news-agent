"""
Gemini-based UPSC relevance classifier and structured note generator.

Two passes:
  1. classify(): one call per article, returns relevance + papers + topics.
     Filter out anything below threshold here so we don't summarize junk.
  2. summarize(): only for articles that survive the filter, returns full notes.

We use Google's google-genai SDK with gemini-2.0-flash on the free tier.
Free tier limits: 15 RPM, 1500 RPD. We pace at ~12 RPM to stay safe.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from prompts import CLASSIFICATION_PROMPT, SUMMARIZATION_PROMPT, UPSC_SYLLABUS_TAXONOMY
from scraper import Article

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# Free tier is 15 RPM. Pace at 5s between calls = 12 RPM with headroom.
RPM_SLEEP_SECONDS = float(os.environ.get("GEMINI_RPM_SLEEP", "5.0"))


@dataclass
class Classification:
    relevant: bool = False
    relevance_score: int = 0
    primary_paper: str = "None"
    secondary_papers: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class Notes:
    headline: str = ""
    one_line_summary: str = ""
    context: str = ""
    key_facts: list[str] = field(default_factory=list)
    prelims_pointers: list[str] = field(default_factory=list)
    mains_angle: str = ""
    possible_questions: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)


@dataclass
class EnrichedArticle:
    article: Article
    classification: Classification
    notes: Notes | None = None


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set")
    return genai.Client(api_key=api_key)


def _extract_json(text: str) -> dict[str, Any]:
    """Gemini with response_mime_type=application/json returns clean JSON.
    Defensive parsing in case of fences or leading prose."""
    text = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    return json.loads(text)


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(min=2, max=30),
    retry=retry_if_exception_type((Exception,)),
    reraise=True,
)
def _call_gemini(client: genai.Client, model: str, prompt: str, max_tokens: int = 1500) -> dict[str, Any]:
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        max_output_tokens=max_tokens,
        temperature=0.2,
    )
    resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
    text = resp.text or ""
    return _extract_json(text)


def classify(article: Article, *, model: str = DEFAULT_MODEL, client: genai.Client | None = None) -> Classification:
    client = client or _client()
    prompt = CLASSIFICATION_PROMPT.format(
        taxonomy=UPSC_SYLLABUS_TAXONOMY,
        title=article.title,
        section=article.section,
        url=article.url,
        content=article.content[:3000],
    )
    try:
        data = _call_gemini(client, model, prompt, max_tokens=600)
    except Exception as e:
        log.warning("classify failed for %s: %s", article.url, e)
        return Classification(reason=f"classification error: {e}")
    return Classification(
        relevant=bool(data.get("relevant", False)),
        relevance_score=int(data.get("relevance_score", 0)),
        primary_paper=str(data.get("primary_paper", "None")),
        secondary_papers=list(data.get("secondary_papers", []) or []),
        topics=list(data.get("topics", []) or []),
        reason=str(data.get("reason", "")),
    )


def summarize(article: Article, classification: Classification, *, model: str = DEFAULT_MODEL, client: genai.Client | None = None) -> Notes:
    client = client or _client()
    prompt = SUMMARIZATION_PROMPT.format(
        title=article.title,
        section=article.section,
        url=article.url,
        primary_paper=classification.primary_paper,
        topics=", ".join(classification.topics),
        content=article.content[:8000],
    )
    try:
        data = _call_gemini(client, model, prompt, max_tokens=2000)
    except Exception as e:
        log.warning("summarize failed for %s: %s", article.url, e)
        return Notes(headline=article.title, one_line_summary="(summarization failed)", context=str(e))
    return Notes(
        headline=str(data.get("headline", article.title)),
        one_line_summary=str(data.get("one_line_summary", "")),
        context=str(data.get("context", "")),
        key_facts=list(data.get("key_facts", []) or []),
        prelims_pointers=list(data.get("prelims_pointers", []) or []),
        mains_angle=str(data.get("mains_angle", "")),
        possible_questions=list(data.get("possible_questions", []) or []),
        related_topics=list(data.get("related_topics", []) or []),
    )


def enrich_articles(
    articles: list[Article],
    *,
    relevance_threshold: int = 6,
    model: str = DEFAULT_MODEL,
) -> list[EnrichedArticle]:
    client = _client()
    results: list[EnrichedArticle] = []
    for i, art in enumerate(articles, 1):
        log.info("[%d/%d] classify: %s", i, len(articles), art.title[:80])
        cls = classify(art, model=model, client=client)
        time.sleep(RPM_SLEEP_SECONDS)  # rate-limit pacing
        ea = EnrichedArticle(article=art, classification=cls)
        if cls.relevant and cls.relevance_score >= relevance_threshold:
            log.info("  -> KEEP (score=%d, paper=%s) — summarizing", cls.relevance_score, cls.primary_paper)
            ea.notes = summarize(art, cls, model=model, client=client)
            time.sleep(RPM_SLEEP_SECONDS)
        else:
            log.info("  -> SKIP (score=%d) reason=%s", cls.relevance_score, cls.reason)
        results.append(ea)
    return results


def kept_only(enriched: list[EnrichedArticle]) -> list[EnrichedArticle]:
    return [e for e in enriched if e.notes is not None]
