"""
pib-upsc-agent
==============
Fetches the latest Press Information Bureau (PIB) press releases, filters and
rewrites them for UPSC relevance using the free Google Gemini API, renders a
PDF briefing, and emails it via Gmail SMTP. Designed to be run once a day by
Windows Task Scheduler (see setup_schedule.bat).

Run manually with:   python agent.py
"""

import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BASE_DIR = Path(__file__).resolve().parent
SEEN_PRIDS_PATH = BASE_DIR / "seen_prids.json"
# Note: PIB's server 302-redirects "Lang=1&Regid=3" (no "reg" param) to a
# Hindi-language edition ("Lang=2&Regid=3&reg=48"). Appending "&reg=48"
# ourselves is what actually keeps the feed in English — verified live.
RSS_URL = "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3&reg=48"
MAX_SEEN_PRIDS = 500
ARTICLE_CHAR_LIMIT = 5000
REQUEST_TIMEOUT = 20
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def log(step, total, message):
    print(f"[{step}/{total}] {message}", flush=True)


# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------

def load_config():
    load_dotenv(BASE_DIR / ".env")

    config = {
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", "").strip(),
        "EMAIL_SENDER": os.getenv("EMAIL_SENDER", "").strip(),
        "EMAIL_APP_PASSWORD": os.getenv("EMAIL_APP_PASSWORD", "").strip(),
        "EMAIL_RECIPIENT": os.getenv("EMAIL_RECIPIENT", "").strip(),
        "SMTP_HOST": os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
        "SMTP_PORT": int(os.getenv("SMTP_PORT", "465").strip() or "465"),
        "GEMINI_MODEL": os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),
        "MAX_RELEASES": int(os.getenv("MAX_RELEASES", "25").strip() or "25"),
    }

    required = ["GEMINI_API_KEY", "EMAIL_SENDER", "EMAIL_APP_PASSWORD", "EMAIL_RECIPIENT"]
    missing = [key for key in required if not config[key]]
    if missing:
        print("ERROR: Missing required .env values: " + ", ".join(missing))
        print("Copy .env.example to .env and fill in these values before running.")
        sys.exit(1)

    return config


# ---------------------------------------------------------------------------
# 2. RSS fetch + PRID parsing
# ---------------------------------------------------------------------------

PRID_RE = re.compile(r"PRID=(\d+)", re.IGNORECASE)


def fetch_rss_items():
    resp = requests.get(RSS_URL, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "xml")
    items = []
    for item in soup.find_all("item"):
        title_tag = item.find("title")
        link_tag = item.find("link")
        if not title_tag or not link_tag:
            continue

        title = title_tag.get_text(strip=True)
        link = link_tag.get_text(strip=True)

        match = PRID_RE.search(link)
        if not match:
            print(f"WARNING: skipping RSS item with no PRID in link: {link}")
            continue

        items.append({"prid": match.group(1), "title": title, "link": link})

    return items


# ---------------------------------------------------------------------------
# 3. seen_prids.json handling
# ---------------------------------------------------------------------------

def load_seen_prids():
    if not SEEN_PRIDS_PATH.exists():
        return []
    try:
        with open(SEEN_PRIDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError('seen_prids.json must contain a JSON list')
        return list(dict.fromkeys(str(p) for p in data))
    except (json.JSONDecodeError, OSError, ValueError):
        print("WARNING: could not read seen_prids.json, treating as empty.")
        return set()


def save_seen_prids(seen_prids):
    trimmed = list(seen_prids)[-MAX_SEEN_PRIDS:]
    with open(SEEN_PRIDS_PATH, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2)


# ---------------------------------------------------------------------------
# 5. Full article fetch + clean
# ---------------------------------------------------------------------------

def fetch_article_text(url):
    resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n".join(p for p in paragraphs if p)

    return text[:ARTICLE_CHAR_LIMIT]


# ---------------------------------------------------------------------------
# 6. Gemini batch call
# ---------------------------------------------------------------------------

GEMINI_PROMPT_TEMPLATE = """You are an expert UPSC Civil Services exam mentor. Below is a batch of \
today's Press Information Bureau (PIB) press releases, each with a title, source URL, and body text.

Your task:
1. Select ONLY the releases relevant to the UPSC syllabus: polity, governance, economy, government \
schemes, environment, science & tech, international relations, internal security, social issues, \
reports/indices.
2. Discard PR fluff, photo captions, congratulatory messages, felicitations, and minor \
regional/administrative notices with no exam relevance.
3. Return STRICT JSON ONLY — no markdown code fences, no commentary before or after — matching \
exactly this schema:

{{
  "overview": "2-3 sentence summary of the day's themes",
  "items": [
    {{
      "title": "...",
      "gs_papers": ["GS2", "GS3"],
      "topic": "...",
      "summary": "4-6 sentence factual summary",
      "prelims_facts": ["...", "..."],
      "mains_angle": "1-2 sentences",
      "source_url": "..."
    }}
  ]
}}

If NONE of the releases are UPSC-relevant, return {{"overview": "", "items": []}}.

Here are the releases:

{releases_block}
"""


def build_gemini_prompt(releases):
    blocks = []
    for r in releases:
        blocks.append(
            f"### {r['title']}\nSource URL: {r['link']}\n\n{r['text']}\n"
        )
    releases_block = "\n---\n".join(blocks)
    return GEMINI_PROMPT_TEMPLATE.format(releases_block=releases_block)


def call_gemini(releases, config):
    from google import genai

    client = genai.Client(api_key=config["GEMINI_API_KEY"], http_options={"timeout": 120000, "retry_options": {"attempts": 1}})
    prompt = build_gemini_prompt(releases)

    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=config["GEMINI_MODEL"] if attempt < 2 else "gemini-3.1-flash-lite",
                contents=prompt,
            )
            break
        except Exception as exc:
            if getattr(exc, "code", None) not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            delay = 15 * (2 ** attempt)
            print(f"WARNING: Gemini temporarily unavailable; retrying in {delay} seconds.", flush=True)
            time.sleep(delay)

    raw_text = (response.text or "").strip()

    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        raise ValueError("Gemini returned an empty response.")

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini response was not valid JSON: {exc}\n---\n{cleaned[:500]}")

    data.setdefault("overview", "")
    data.setdefault("items", [])
    return data


# ---------------------------------------------------------------------------
# 7. PDF rendering
# ---------------------------------------------------------------------------

def clean_text(text):
    """Make Gemini-generated text safe for reportlab's Paragraph markup parser."""
    text = str(text).replace("₹", "Rs. ")
    return xml_escape(text)


def build_pdf(data, date_str, out_path):
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=20, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"], fontSize=10,
        textColor=colors.grey, spaceAfter=16,
    )
    section_heading_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"], fontSize=13,
        spaceBefore=6, spaceAfter=6, textColor=colors.HexColor("#1a3a5c"),
    )
    item_title_style = ParagraphStyle(
        "ItemTitle", parent=styles["Heading3"], fontSize=12,
        spaceBefore=14, spaceAfter=4, textColor=colors.HexColor("#0d2438"),
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=6,
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"], fontSize=9.5, leading=13,
        spaceAfter=2, textColor=colors.HexColor("#333333"),
    )
    tag_style = ParagraphStyle(
        "Tag", parent=styles["Normal"], fontSize=9, textColor=colors.white,
    )
    link_style = ParagraphStyle(
        "Link", parent=styles["Normal"], fontSize=9.5, spaceBefore=4,
        textColor=colors.HexColor("#1a5cbf"),
    )

    story = []
    story.append(Paragraph("Daily PIB UPSC Current Affairs Brief", title_style))
    story.append(Paragraph(date_str, subtitle_style))

    overview = data.get("overview") or ""
    if overview:
        story.append(Paragraph("Overview", section_heading_style))
        story.append(Paragraph(clean_text(overview), body_style))
        story.append(Spacer(1, 0.4 * cm))

    items = data.get("items") or []

    for idx, item in enumerate(items, start=1):
        title = item.get("title") or "Untitled release"
        story.append(Paragraph(f"{idx}. {clean_text(title)}", item_title_style))

        gs_papers = item.get("gs_papers") or []
        if gs_papers:
            cells = []
            col_widths = []
            for i, tag in enumerate(gs_papers):
                if i > 0:
                    cells.append("")
                    col_widths.append(0.2 * cm)
                cells.append(Paragraph(clean_text(tag), tag_style))
                col_widths.append(1.6 * cm)

            tag_row = Table([cells], colWidths=col_widths, hAlign="LEFT")
            row_style = [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
            for i in range(0, len(cells), 2):
                row_style.append(("BACKGROUND", (i, 0), (i, 0), colors.HexColor("#2e6da4")))
            tag_row.setStyle(TableStyle(row_style))
            story.append(tag_row)
            story.append(Spacer(1, 0.15 * cm))

        topic = item.get("topic") or ""
        if topic:
            story.append(Paragraph(f"<b>Topic:</b> {clean_text(topic)}", label_style))

        summary = item.get("summary") or ""
        if summary:
            story.append(Paragraph(clean_text(summary), body_style))

        prelims_facts = item.get("prelims_facts") or []
        if prelims_facts:
            story.append(Paragraph("<b>Prelims pointers:</b>", label_style))
            bullet_items = [
                ListItem(Paragraph(clean_text(fact), body_style))
                for fact in prelims_facts
            ]
            story.append(ListFlowable(bullet_items, bulletType="bullet", leftIndent=14))

        mains_angle = item.get("mains_angle") or ""
        if mains_angle:
            story.append(Paragraph(f"<b>Mains angle:</b> {clean_text(mains_angle)}", body_style))

        source_url = item.get("source_url") or ""
        if source_url:
            story.append(Paragraph(
                f'<link href="{clean_text(source_url)}" color="#1a5cbf">Read full release &rarr;</link>',
                link_style,
            ))

        story.append(Spacer(1, 0.3 * cm))

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        title="Daily PIB UPSC Brief",
    )
    doc.build(story)
    return out_path


# ---------------------------------------------------------------------------
# 8. Email
# ---------------------------------------------------------------------------

def send_email(pdf_path, date_str, config):
    msg = MIMEMultipart()
    msg["From"] = config["EMAIL_SENDER"]
    msg["To"] = config["EMAIL_RECIPIENT"]
    msg["Subject"] = f"Daily PIB UPSC Brief - {date_str}"

    body = (
        f"Attached is your Daily PIB UPSC Current Affairs Brief for {date_str}.\n\n"
        "Generated automatically from PIB press releases and filtered for UPSC relevance.\n"
    )
    msg.attach(MIMEText(body, "plain"))

    with open(pdf_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="pdf")
    attachment.add_header(
        "Content-Disposition", "attachment", filename=Path(pdf_path).name
    )
    msg.attach(attachment)

    with smtplib.SMTP_SSL(config["SMTP_HOST"], config["SMTP_PORT"], timeout=60) as server:
        server.login(config["EMAIL_SENDER"], config["EMAIL_APP_PASSWORD"])
        server.sendmail(config["EMAIL_SENDER"], config["EMAIL_RECIPIENT"], msg.as_string())


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    total_steps = 5
    today = datetime.now(ZoneInfo('Asia/Kolkata'))
    date_str = today.strftime("%Y-%m-%d")

    config = load_config()

    log(1, total_steps, "Fetching PIB RSS feed...")
    try:
        rss_items = fetch_rss_items()
    except requests.RequestException as exc:
        print(f"ERROR: Could not fetch PIB RSS feed: {exc}")
        sys.exit(1)

    seen_prids = load_seen_prids()
    new_items = [item for item in rss_items if item["prid"] not in seen_prids]
    new_items = new_items[: config["MAX_RELEASES"]]

    print(f"    Found {len(rss_items)} total feed items, {len(new_items)} new (capped at {config['MAX_RELEASES']}).")

    if not new_items:
        print("No new PIB releases since last run. Exiting cleanly, no email sent.")
        sys.exit(0)

    log(2, total_steps, f"Fetching full text for {len(new_items)} new release(s)...")
    fetched_releases = []
    fetched_prids = []
    for item in new_items:
        try:
            text = fetch_article_text(item["link"])
        except requests.RequestException as exc:
            print(f"WARNING: failed to fetch '{item['title']}' ({item['link']}): {exc}")
            continue

        if not text:
            print(f"WARNING: no body text extracted for '{item['title']}' ({item['link']}); skipping.")
            continue

        fetched_releases.append({
            "prid": item["prid"],
            "title": item["title"],
            "link": item["link"],
            "text": text,
        })
        fetched_prids.append(item["prid"])

    if not fetched_releases:
        print("No releases could be fetched successfully this run. Exiting cleanly, no email sent.")
        sys.exit(0)

    log(3, total_steps, f"Sending {len(fetched_releases)} release(s) to Gemini for UPSC filtering...")
    try:
        gemini_data = call_gemini(fetched_releases, config)
    except Exception as exc:  # network, API, or parsing errors
        print(f"ERROR: Gemini call failed: {exc}")
        sys.exit(1)

    items = gemini_data.get("items") or []
    if not items:
        print("Gemini found no UPSC-relevant releases today. Marking releases as seen, no email sent.")
        seen_prids.extend(p for p in fetched_prids if p not in seen_prids)
        save_seen_prids(seen_prids)
        sys.exit(0)

    print(f"    Gemini kept {len(items)} UPSC-relevant item(s).")

    log(4, total_steps, "Building PDF report...")
    pdf_filename = f"PIB_UPSC_{date_str}.pdf"
    pdf_path = BASE_DIR / pdf_filename
    try:
        build_pdf(gemini_data, today.strftime("%d %B %Y"), pdf_path)
    except Exception as exc:
        print(f"ERROR: Failed to build PDF: {exc}")
        sys.exit(1)
    print(f"    Saved {pdf_path}")

    log(5, total_steps, f"Emailing PDF to {config['EMAIL_RECIPIENT']}...")
    try:
        send_email(pdf_path, date_str, config)
    except smtplib.SMTPAuthenticationError:
        print(
            "ERROR: SMTP authentication failed. Check EMAIL_SENDER / EMAIL_APP_PASSWORD in .env "
            "(Gmail requires a 16-character App Password, not your normal password)."
        )
        sys.exit(1)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"ERROR: Failed to send email: {exc}")
        sys.exit(1)

    seen_prids.extend(p for p in fetched_prids if p not in seen_prids)
    save_seen_prids(seen_prids)

    print("Done. Email sent successfully.")


if __name__ == "__main__":
    main()

