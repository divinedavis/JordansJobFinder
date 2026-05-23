"""Resume upload, parsing, PDF rendering, and tailored-resume sync hook."""
import io
import json
import os

from docx import Document
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


SAMPLE_STRUCTURED = {
    "name": "DIVINE DAVIS",
    "contact_line_1": "New York, NY | 717-659-9140 | divinejdavis@gmail.com",
    "contact_line_2": "linkedin.com/in/divinejdavis | divinedavis.com",
    "summary": "Senior Product Manager with 10 years of experience driving digital platform transformations.",
    "experience": [
        {
            "company": "JPMorgan Chase",
            "title": "Vice President, Technical Program & Product Manager",
            "dates": "August 2021 – Present",
            "bullets": [
                "Manage elements of the digital platform strategy for 50 mission-critical applications.",
                "Spearheaded an AI-powered Technical Co-pilot agent.",
            ],
        }
    ],
    "competencies": [
        {"label": "Product Line Strategy", "items": "Consumer Product Development, Benefit Strategies."},
    ],
    "education": [{"degree": "B.S. Computer Science", "school": "Claflin University"}],
    "tools": "Jira, Confluence, SQL, Tableau",
}


def _make_docx_bytes(text: str) -> bytes:
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    y = 750
    for line in text.splitlines():
        c.drawString(72, y, line)
        y -= 16
    c.showPage()
    c.save()
    return buf.getvalue()


def test_resume_page_renders_for_logged_in_user(signed_in_client):
    response = signed_in_client.get("/resume")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Your base resume" in body


def test_resume_page_redirects_when_unauthenticated(client):
    response = client.get("/resume")
    assert response.status_code == 302
    assert "/sign-in" in response.headers["Location"]


def test_resume_upload_accepts_docx(signed_in_client, db_session, app):
    from app.models import BaseResume, User

    data = {
        "resume": (io.BytesIO(_make_docx_bytes(
            "Jordan Doe\nSenior Product Manager\nSkills: agile, cloud, API design\n"
        )), "resume.docx"),
    }
    response = signed_in_client.post(
        "/resume/upload",
        data=data,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert "/resume" in response.headers["Location"]

    user = db_session.query(User).first()
    resume = db_session.query(BaseResume).filter(BaseResume.user_id == user.id).one()
    assert "Senior Product Manager" in resume.extracted_text
    assert os.path.exists(resume.file_path)


def test_resume_upload_accepts_pdf(signed_in_client, db_session):
    from app.models import BaseResume, User

    data = {
        "resume": (io.BytesIO(_make_pdf_bytes("Jordan Doe Product Manager")), "resume.pdf"),
    }
    response = signed_in_client.post(
        "/resume/upload",
        data=data,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    user = db_session.query(User).first()
    resume = db_session.query(BaseResume).filter(BaseResume.user_id == user.id).one()
    assert "Jordan" in resume.extracted_text or "Product" in resume.extracted_text


def test_resume_upload_rejects_unknown_filetype(signed_in_client):
    data = {"resume": (io.BytesIO(b"not a resume"), "resume.txt")}
    response = signed_in_client.post(
        "/resume/upload",
        data=data,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    # Should redirect back to /resume with a flash, NOT 500.


def test_resume_upload_handles_malformed_pdf_gracefully(signed_in_client):
    """A corrupt 'PDF' (just bytes ending in .pdf) must not 500 — should flash + redirect."""
    data = {"resume": (io.BytesIO(b"%PDF-1.4 garbage not a real pdf"), "broken.pdf")}
    response = signed_in_client.post(
        "/resume/upload",
        data=data,
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert "/resume" in response.headers["Location"]


def test_render_resume_pdf_produces_valid_pdf(app, tmp_path):
    from app.resumes import render_resume_pdf

    out = tmp_path / "out.pdf"
    with app.app_context():
        render_resume_pdf(SAMPLE_STRUCTURED, str(out))
    assert out.exists()
    pdf_bytes = out.read_bytes()
    assert pdf_bytes[:4] == b"%PDF"
    # Pull text back out to sanity-check expected sections rendered.
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    assert "DIVINE DAVIS" in text
    assert "PROFESSIONAL EXPERIENCE" in text
    assert "JPMorgan Chase" in text
    assert "August 2021" in text
    assert "CORE COMPETENCIES" in text
    assert "EDUCATION" in text
    assert "Claflin" in text
    assert "Jira" in text


def test_generate_tailored_resume_returns_none_without_api_key(app, tmp_path):
    """No ANTHROPIC_API_KEY → tailored generation is skipped (returns None)."""
    from app.resumes import generate_tailored_resume

    class _Job:
        id = 1; company = "Acme"; title = "PM"; description = "Looking for a PM."

    class _User:
        id = 1

    class _Base:
        extracted_text = "Jordan's base resume content."

    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = ""
        app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")
        path = generate_tailored_resume(user=_User(), job=_Job(), base_resume=_Base())
    assert path is None


def test_sync_skips_tailored_resumes_without_api_key(app, db_session, tmp_path):
    """The daily sync hook returns 0 and creates no TailoredResume rows
    when the API key is missing — no fake/base-text PDFs are produced."""
    from app.models import BaseResume, Job, JobMatch, SavedSearch, TailoredResume, User
    from app.sync import generate_tailored_resumes

    user = User(email="resumetest@example.com")
    user.set_password("password123")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    db_session.add(SavedSearch(
        user_id=user.id,
        title_slug="technical-product-manager",
        experience_bucket="7-9",
        city_1="New York, NY", city_2="Atlanta, GA", city_3="Miami, FL",
        city_4="Dallas, TX", city_5="Houston, TX", city_6="Washington, DC",
    ))
    db_session.add(BaseResume(
        user_id=user.id, filename="resume.docx",
        file_path="/tmp/resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extracted_text="Jordan Doe — Senior Product Manager",
    ))
    job = Job(
        source="test", company="Acme", title="Senior Product Manager",
        normalized_title="senior product manager",
        url="https://example.com/jobs/1", city="nyc", location="New York, NY",
        description="Looking for a senior PM.", is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    saved = db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id).one()
    db_session.add(JobMatch(saved_search_id=saved.id, user_id=user.id, job_id=job.id))
    db_session.commit()
    user_id = user.id

    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = ""
        app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")
        created = generate_tailored_resumes()

    assert created == 0
    with app.app_context():
        from app.db import get_db
        fresh = get_db()
        rows = fresh.query(TailoredResume).filter(TailoredResume.user_id == user_id).all()
        assert rows == []


def test_sync_generates_tailored_resume_with_mocked_anthropic(app, db_session, monkeypatch, tmp_path):
    """With API key + mocked Anthropic returning structured JSON, the sync
    hook creates one TailoredResume per (user, job) match and writes a PDF."""
    from app.models import BaseResume, Job, JobMatch, SavedSearch, TailoredResume, User
    from app.sync import generate_tailored_resumes

    user = User(email="mocked@example.com")
    user.set_password("password123")
    db_session.add(user); db_session.commit(); db_session.refresh(user)
    db_session.add(SavedSearch(
        user_id=user.id, title_slug="technical-product-manager",
        experience_bucket="7-9",
        city_1="New York, NY", city_2="Atlanta, GA", city_3="Miami, FL",
        city_4="Dallas, TX", city_5="Houston, TX", city_6="Washington, DC",
    ))
    db_session.add(BaseResume(
        user_id=user.id, filename="resume.docx",
        file_path="/tmp/resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extracted_text="Jordan Doe — Senior Product Manager",
    ))
    job = Job(
        source="test", company="Acme", title="Senior Product Manager",
        normalized_title="senior product manager",
        url="https://example.com/jobs/m", city="nyc", location="New York, NY",
        description="Looking for a senior PM.", is_technical=True,
    )
    db_session.add(job); db_session.commit(); db_session.refresh(job)
    saved = db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id).one()
    db_session.add(JobMatch(saved_search_id=saved.id, user_id=user.id, job_id=job.id))
    db_session.commit()
    user_id = user.id; job_id = job.id

    # Mock the Anthropic SDK so it returns valid structured JSON.
    class _Block:
        type = "text"
        text = json.dumps(SAMPLE_STRUCTURED)

    class _Message:
        content = [_Block()]

    class _Messages:
        def create(self, **kw):
            return _Message()

    class _Client:
        def __init__(self, api_key):
            self.messages = _Messages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Client)

    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = "sk-test"
        app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")
        created = generate_tailored_resumes()

    assert created == 1
    with app.app_context():
        from app.db import get_db
        fresh = get_db()
        tailored = fresh.query(TailoredResume).filter(
            TailoredResume.user_id == user_id, TailoredResume.job_id == job_id,
        ).one()
        assert os.path.exists(tailored.pdf_path)
        assert open(tailored.pdf_path, "rb").read()[:4] == b"%PDF"


def test_tailor_resume_structured_parses_json_with_markdown_fences(app, monkeypatch):
    """Anthropic sometimes wraps JSON in ```json fences — strip and parse."""
    from app import resumes as resumes_module

    class _Block:
        type = "text"
        text = "```json\n" + json.dumps(SAMPLE_STRUCTURED) + "\n```"

    class _Message:
        content = [_Block()]

    class _Messages:
        def create(self, **kw):
            return _Message()

    class _Client:
        def __init__(self, api_key):
            self.messages = _Messages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Client)

    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = "sk-test"
        result = resumes_module.tailor_resume_structured(
            base_text="base", job_title="PM", company="Acme",
            job_description="Looking for a PM.",
        )
    assert result is not None
    assert result["name"] == "DIVINE DAVIS"
    assert result["experience"][0]["company"] == "JPMorgan Chase"


def test_tailor_resume_structured_returns_none_on_bad_json(app, monkeypatch):
    """Malformed AI output → None (no crash, no broken PDF)."""
    from app import resumes as resumes_module

    class _Block:
        type = "text"
        text = "Sorry, I cannot help with that."

    class _Message:
        content = [_Block()]

    class _Messages:
        def create(self, **kw):
            return _Message()

    class _Client:
        def __init__(self, api_key):
            self.messages = _Messages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Client)

    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = "sk-test"
        result = resumes_module.tailor_resume_structured(
            base_text="base", job_title="PM", company="Acme",
            job_description="Looking for a PM.",
        )
    assert result is None
