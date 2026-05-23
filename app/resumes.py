"""Resume upload, text extraction, AI tailoring, and PDF rendering.

The rendered PDF mirrors the reference resume style:
- Helvetica throughout (built into reportlab)
- Accent color #2356B2 (sampled from Divine_Davis_Mastercard_NAM_Consumer_Credit.pdf)
- Centered name header + contact lines, blue rule
- Section headings in accent color, all caps, light grey underline
- Each experience entry uses a 2-col layout: company (blue, left) + dates (bold, right),
  then the role title in bold, then bullet points
- Core Competencies rendered as a 2-col table (bold label + items)
- Education & Tools at the bottom
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from flask import current_app
from reportlab.lib.colors import HexColor, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)


ACCENT = HexColor("#2356B2")
LIGHT_RULE = HexColor("#C8C8C8")

ACCEPTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

# Anthropic prompt: produce structured JSON so the renderer can always lay out
# the same template regardless of the candidate.
RESUME_PROMPT = """You are a resume tailoring assistant. Given a candidate's base resume and a job posting, produce a tailored resume that emphasizes the candidate's most relevant experience for that role.

CRITICAL RULES:
- Do NOT invent employers, titles, dates, degrees, skills, or accomplishments.
- Use only information present in the base resume — rewording is fine, fabrication is not.
- Tailor the SUMMARY paragraph and ORDER OF BULLETS toward the job posting. Drop bullets that aren't relevant.

Output ONLY a JSON object with this exact shape. No markdown fences, no commentary:

{{
  "name": "FULL NAME IN ALL CAPS",
  "contact_line_1": "City, ST | phone | email",
  "contact_line_2": "linkedin.com/in/handle | website",
  "summary": "2-4 sentence professional summary tailored to this job. Lead with the candidate's seniority and years of experience.",
  "experience": [
    {{
      "company": "Company name",
      "title": "Role title",
      "dates": "Month Year – Month Year (or Present)",
      "bullets": ["Bullet 1.", "Bullet 2.", "Bullet 3."]
    }}
  ],
  "competencies": [
    {{"label": "Group 1 Label", "items": "Comma-separated items."}},
    {{"label": "Group 2 Label", "items": "Comma-separated items."}},
    {{"label": "Group 3 Label", "items": "Comma-separated items."}}
  ],
  "education": [
    {{"degree": "Degree name", "school": "School name"}}
  ],
  "tools": "Tool1, Tool2, Tool3"
}}

If a field is unknown from the base resume, use an empty string or empty array — but DO populate every key.

=== JOB POSTING ===
Title: {job_title}
Company: {company}

{job_description}

=== BASE RESUME ===
{base_text}

=== TAILORED RESUME JSON ==="""


class ResumeError(Exception):
    """Raised on resume processing failures the user should see."""


def _ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def detect_kind(filename: str, content_type: str) -> str:
    """Return 'pdf' or 'docx'. Raises ResumeError for anything else."""
    if content_type in ACCEPTED_CONTENT_TYPES:
        return ACCEPTED_CONTENT_TYPES[content_type]
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith(".docx"):
        return "docx"
    raise ResumeError("Upload must be a PDF or DOCX file.")


def extract_text(raw_bytes: bytes, kind: str) -> str:
    if kind == "pdf":
        return _extract_pdf_text(raw_bytes)
    if kind == "docx":
        return _extract_docx_text(raw_bytes)
    raise ResumeError(f"Unsupported resume kind: {kind}")


def _extract_pdf_text(raw_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as exc:  # pragma: no cover
            logger.warning("PDF page extract failed: %s", exc)
    text = "\n".join(parts).strip()
    if not text:
        raise ResumeError("Could not extract text from the PDF.")
    return text


def _extract_docx_text(raw_bytes: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(raw_bytes))
    parts = [p.text for p in doc.paragraphs if p.text]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text:
                    parts.append(cell.text)
    text = "\n".join(parts).strip()
    if not text:
        raise ResumeError("Could not extract text from the DOCX file.")
    return text


def save_base_resume(user_id: int, filename: str, raw_bytes: bytes, kind: str) -> str:
    upload_dir = current_app.config["RESUME_UPLOAD_DIR"]
    _ensure_dir(upload_dir)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename or f"resume.{kind}")
    out_path = os.path.join(upload_dir, f"user-{user_id}-{safe_name}")
    with open(out_path, "wb") as fh:
        fh.write(raw_bytes)
    return out_path


def tailor_resume_structured(
    base_text: str, job_title: str, company: str, job_description: str
) -> Optional[dict]:
    """Call Anthropic and return a structured resume dict, or None if the API
    key is missing or the response isn't parseable JSON."""
    api_key = current_app.config.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping tailored resume generation")
        return None

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    model = current_app.config.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    prompt = RESUME_PROMPT.format(
        job_title=job_title,
        company=company,
        job_description=job_description or "(no description provided)",
        base_text=base_text,
    )
    message = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(
        block.text for block in message.content if getattr(block, "type", "") == "text"
    ).strip()
    # Tolerate accidental markdown fences.
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Anthropic returned non-JSON resume: %s", exc)
        return None


# ── PDF rendering ────────────────────────────────────────────────────────────

def _styles():
    base = ParagraphStyle(
        "Base", fontName="Helvetica", fontSize=10, leading=13, textColor=black
    )
    return {
        "name": ParagraphStyle(
            "Name", parent=base, fontName="Helvetica-Bold", fontSize=24,
            textColor=ACCENT, alignment=TA_CENTER, leading=28, spaceAfter=4,
        ),
        "contact": ParagraphStyle(
            "Contact", parent=base, alignment=TA_CENTER, fontSize=10,
            textColor=black, leading=13,
        ),
        "summary": ParagraphStyle(
            "Summary", parent=base, fontSize=10.5, leading=14, spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "Section", parent=base, fontName="Helvetica-Bold", fontSize=12.5,
            textColor=ACCENT, leading=15, spaceBefore=10, spaceAfter=2,
        ),
        "company": ParagraphStyle(
            "Company", parent=base, fontName="Helvetica-Bold", fontSize=11,
            textColor=ACCENT, leading=14,
        ),
        "dates": ParagraphStyle(
            "Dates", parent=base, fontName="Helvetica-Bold", fontSize=10,
            alignment=TA_RIGHT, leading=14,
        ),
        "role": ParagraphStyle(
            "Role", parent=base, fontName="Helvetica-Bold", fontSize=10.5,
            leading=13, spaceAfter=2,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base, fontSize=10, leading=13, leftIndent=14,
            bulletIndent=2, spaceAfter=2,
        ),
        "comp_label": ParagraphStyle(
            "CompLabel", parent=base, fontName="Helvetica-Bold", fontSize=10,
            leading=13,
        ),
        "comp_items": ParagraphStyle(
            "CompItems", parent=base, fontSize=10, leading=13,
        ),
        "edu": ParagraphStyle(
            "Edu", parent=base, fontSize=10.5, leading=14, spaceAfter=4,
        ),
    }


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _section_heading(label: str, styles) -> list:
    return [
        Paragraph(label.upper(), styles["section"]),
        HRFlowable(width="100%", thickness=0.5, color=LIGHT_RULE,
                   spaceBefore=0, spaceAfter=6),
    ]


def _header_block(data: dict, styles) -> list:
    blocks = []
    name = _escape(data.get("name", ""))
    if name:
        blocks.append(Paragraph(name, styles["name"]))
    for key in ("contact_line_1", "contact_line_2"):
        line = _escape(data.get(key, ""))
        if line:
            blocks.append(Paragraph(line, styles["contact"]))
    blocks.append(Spacer(1, 4))
    blocks.append(HRFlowable(width="100%", thickness=1.5, color=ACCENT,
                             spaceBefore=2, spaceAfter=10))
    return blocks


def _experience_block(data: dict, styles) -> list:
    blocks = _section_heading("Professional Experience", styles)
    for role in data.get("experience", []) or []:
        company = _escape(role.get("company", ""))
        dates = _escape(role.get("dates", ""))
        title = _escape(role.get("title", ""))
        bullets = role.get("bullets", []) or []
        if not (company or title or bullets):
            continue
        row = Table(
            [[Paragraph(company, styles["company"]), Paragraph(dates, styles["dates"])]],
            colWidths=[4.2 * inch, 2.8 * inch],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]),
        )
        entry = [row]
        if title:
            entry.append(Paragraph(title, styles["role"]))
        for b in bullets:
            entry.append(Paragraph(f"• {_escape(b)}", styles["bullet"]))
        entry.append(Spacer(1, 6))
        blocks.append(KeepTogether(entry))
    return blocks


def _competencies_block(data: dict, styles) -> list:
    comps = data.get("competencies", []) or []
    if not comps:
        return []
    blocks = _section_heading("Core Competencies", styles)
    rows = []
    for c in comps:
        label = _escape(c.get("label", ""))
        items = _escape(c.get("items", ""))
        if not (label or items):
            continue
        rows.append([
            Paragraph(f"{label}:" if label else "", styles["comp_label"]),
            Paragraph(items, styles["comp_items"]),
        ])
    if rows:
        blocks.append(Table(
            rows,
            colWidths=[1.9 * inch, 5.1 * inch],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]),
        ))
    return blocks


def _education_block(data: dict, styles) -> list:
    edu = data.get("education", []) or []
    tools = (data.get("tools") or "").strip()
    if not (edu or tools):
        return []
    blocks = _section_heading("Education & Technical Skills", styles)
    for e in edu:
        degree = _escape(e.get("degree", ""))
        school = _escape(e.get("school", ""))
        if degree and school:
            blocks.append(Paragraph(
                f"<b>{degree}</b> | {school}", styles["edu"]))
        elif degree:
            blocks.append(Paragraph(f"<b>{degree}</b>", styles["edu"]))
        elif school:
            blocks.append(Paragraph(school, styles["edu"]))
    if tools:
        blocks.append(Paragraph(
            f"<b>Tools:</b> {_escape(tools)}", styles["edu"]))
    return blocks


def render_resume_pdf(data: dict, output_path: str, title: str = "Tailored Resume") -> str:
    """Render the structured resume dict to a PDF at output_path."""
    _ensure_dir(os.path.dirname(output_path))
    doc = SimpleDocTemplate(
        output_path,
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=title,
    )
    styles = _styles()
    flowables = []
    flowables.extend(_header_block(data, styles))
    summary = (data.get("summary") or "").strip()
    if summary:
        flowables.append(Paragraph(_escape(summary), styles["summary"]))
    flowables.extend(_experience_block(data, styles))
    flowables.extend(_competencies_block(data, styles))
    flowables.extend(_education_block(data, styles))
    doc.build(flowables)
    return output_path


def tailored_pdf_path(user_id: int, job_id: int) -> str:
    base_dir = current_app.config["RESUME_TAILORED_DIR"]
    return os.path.join(base_dir, f"user-{user_id}", f"job-{job_id}.pdf")


def generate_tailored_resume(user, job, base_resume) -> Optional[str]:
    """End-to-end: call AI, render PDF, return path. Returns None if no
    base resume, no API key, or the AI response isn't valid JSON."""
    if not base_resume or not base_resume.extracted_text:
        return None
    structured = tailor_resume_structured(
        base_text=base_resume.extracted_text,
        job_title=job.title,
        company=job.company,
        job_description=job.description or "",
    )
    if not structured:
        return None
    out_path = tailored_pdf_path(user.id, job.id)
    render_resume_pdf(structured, out_path, title=f"{job.company} — Tailored Resume")
    return out_path
