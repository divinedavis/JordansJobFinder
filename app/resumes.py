"""Resume upload, text extraction, AI tailoring, and PDF rendering."""
from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path
from typing import Optional

from flask import current_app
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

logger = logging.getLogger(__name__)


ACCEPTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


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
        except Exception as exc:  # pragma: no cover — surfacing parser oddities
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
    """Persist the uploaded file to disk and return the absolute path."""
    upload_dir = current_app.config["RESUME_UPLOAD_DIR"]
    _ensure_dir(upload_dir)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename or f"resume.{kind}")
    out_path = os.path.join(upload_dir, f"user-{user_id}-{safe_name}")
    with open(out_path, "wb") as fh:
        fh.write(raw_bytes)
    return out_path


def tailor_resume_text(base_text: str, job_title: str, company: str, job_description: str) -> str:
    """Call the Anthropic API and return tailored resume text.

    Returns the base text unchanged if no API key is configured (so the rest
    of the pipeline still produces *something* the user can download).
    """
    api_key = current_app.config.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — falling back to base resume text")
        return base_text

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    model = current_app.config.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    prompt = (
        "You are a resume tailoring assistant. Rewrite the candidate's resume "
        "so it emphasizes the experience and skills most relevant to the job "
        "posting below. Keep the original truthful content — do not invent "
        "employers, titles, dates, or skills the candidate does not have. "
        "Output ONLY the tailored resume text, with clear section headings "
        "(Summary, Experience, Skills, Education). Use plain text — no "
        "markdown bullets, no code fences."
        f"\n\n=== JOB POSTING ===\nTitle: {job_title}\nCompany: {company}\n\n"
        f"{job_description or '(no description provided)'}"
        f"\n\n=== BASE RESUME ===\n{base_text}"
        "\n\n=== TAILORED RESUME ===\n"
    )
    message = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    chunks = [block.text for block in message.content if getattr(block, "type", "") == "text"]
    tailored = "\n".join(chunks).strip()
    return tailored or base_text


def render_text_as_pdf(text: str, output_path: str, title: str = "Tailored Resume") -> str:
    """Render plain text to a PDF file. Returns the path written."""
    _ensure_dir(os.path.dirname(output_path))
    doc = SimpleDocTemplate(
        output_path,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=title,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        spaceAfter=6,
    )
    heading = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        spaceBefore=10,
        spaceAfter=4,
    )

    flowables = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flowables.append(Spacer(1, 6))
            continue
        # Heuristic: ALL-CAPS or "Section:" lines render as headings.
        if (line.isupper() and len(line) <= 60) or re.match(r"^[A-Z][A-Za-z &/]+:$", line):
            flowables.append(Paragraph(line.rstrip(":"), heading))
        else:
            safe = (
                line.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            flowables.append(Paragraph(safe, body))
    doc.build(flowables)
    return output_path


def tailored_pdf_path(user_id: int, job_id: int) -> str:
    base_dir = current_app.config["RESUME_TAILORED_DIR"]
    return os.path.join(base_dir, f"user-{user_id}", f"job-{job_id}.pdf")


def generate_tailored_resume(user, job, base_resume) -> Optional[str]:
    """End-to-end: call the AI, render the PDF, return the PDF path.

    Returns None if the user has no base resume (nothing to tailor).
    """
    if not base_resume or not base_resume.extracted_text:
        return None
    tailored_text = tailor_resume_text(
        base_text=base_resume.extracted_text,
        job_title=job.title,
        company=job.company,
        job_description=job.description or "",
    )
    out_path = tailored_pdf_path(user.id, job.id)
    render_text_as_pdf(tailored_text, out_path, title=f"{job.company} — Tailored Resume")
    return out_path
