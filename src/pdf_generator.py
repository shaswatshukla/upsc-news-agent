"""
Builds a daily UPSC-notes PDF from enriched articles using ReportLab.
Deliberately plain layout — readability over design.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
    ListFlowable,
    ListItem,
)

from classifier import EnrichedArticle

log = logging.getLogger(__name__)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=20, leading=24, spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontSize=11, textColor=colors.grey, spaceAfter=18),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=14, leading=18, spaceBefore=14, spaceAfter=4, textColor=colors.HexColor("#1a365d")),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=11, leading=14, spaceBefore=8, spaceAfter=2, textColor=colors.HexColor("#2c5282")),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=10.5, leading=14, alignment=TA_JUSTIFY, spaceAfter=4),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontSize=9, textColor=colors.grey, spaceAfter=6),
        "tag": ParagraphStyle("tag", parent=base["Normal"], fontSize=9, textColor=colors.HexColor("#2f855a"), spaceAfter=2),
        "bullet": ParagraphStyle("bullet", parent=base["Normal"], fontSize=10.5, leading=14, leftIndent=10, alignment=TA_LEFT),
    }


def _bullets(items: list[str], style: ParagraphStyle) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(_escape(it), style), leftIndent=12) for it in items],
        bulletType="bullet",
        start="•",
        bulletFontSize=10,
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(enriched_kept: list[EnrichedArticle], date: datetime, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=f"UPSC Daily Notes — {date.strftime('%d %b %Y')}",
        author="UPSC News Agent",
    )

    flow = []
    flow.append(Paragraph("UPSC Daily Notes — Indian Express", styles["title"]))
    flow.append(Paragraph(f"{date.strftime('%A, %d %B %Y')} · {len(enriched_kept)} articles", styles["subtitle"]))

    # Index table
    flow.append(Paragraph("Today's Articles", styles["h2"]))
    index_rows = [["#", "Section", "Paper", "Score", "Headline"]]
    for i, ea in enumerate(enriched_kept, 1):
        index_rows.append([
            str(i),
            ea.article.section,
            ea.classification.primary_paper,
            str(ea.classification.relevance_score),
            Paragraph(_escape(ea.notes.headline if ea.notes else ea.article.title), styles["body"]),
        ])
    tbl = Table(index_rows, colWidths=[0.8 * cm, 2.2 * cm, 1.6 * cm, 1.4 * cm, 11 * cm], repeatRows=1)
    tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
        ])
    )
    flow.append(tbl)
    flow.append(PageBreak())

    # Per-article notes
    for i, ea in enumerate(enriched_kept, 1):
        if not ea.notes:
            continue
        n = ea.notes
        flow.append(Paragraph(f"{i}. {_escape(n.headline)}", styles["h2"]))
        meta_bits = [
            f"<b>Section:</b> {_escape(ea.article.section)}",
            f"<b>Paper:</b> {_escape(ea.classification.primary_paper)}",
            f"<b>Score:</b> {ea.classification.relevance_score}/10",
            f"<b>Topics:</b> {_escape(', '.join(ea.classification.topics))}",
        ]
        flow.append(Paragraph(" · ".join(meta_bits), styles["meta"]))
        flow.append(Paragraph(f'<a href="{ea.article.url}">Read original</a>', styles["meta"]))

        if n.one_line_summary:
            flow.append(Paragraph("<b>In one line</b>", styles["h3"]))
            flow.append(Paragraph(_escape(n.one_line_summary), styles["body"]))

        if n.context:
            flow.append(Paragraph("<b>Context</b>", styles["h3"]))
            flow.append(Paragraph(_escape(n.context), styles["body"]))

        if n.key_facts:
            flow.append(Paragraph("<b>Key facts</b>", styles["h3"]))
            flow.append(_bullets(n.key_facts, styles["bullet"]))

        if n.prelims_pointers:
            flow.append(Paragraph("<b>Prelims pointers</b>", styles["h3"]))
            flow.append(_bullets(n.prelims_pointers, styles["bullet"]))

        if n.mains_angle:
            flow.append(Paragraph("<b>Mains angle</b>", styles["h3"]))
            flow.append(Paragraph(_escape(n.mains_angle), styles["body"]))

        if n.possible_questions:
            flow.append(Paragraph("<b>Possible questions</b>", styles["h3"]))
            flow.append(_bullets(n.possible_questions, styles["bullet"]))

        if n.related_topics:
            flow.append(Paragraph("<b>Related topics for revision</b>", styles["h3"]))
            flow.append(Paragraph(_escape(", ".join(n.related_topics)), styles["body"]))

        flow.append(Spacer(1, 0.4 * cm))
        if i < len(enriched_kept):
            flow.append(PageBreak())

    doc.build(flow)
    log.info("PDF written: %s", out_path)
    return out_path
