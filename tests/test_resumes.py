"""Resume upload, parsing, PDF rendering, and tailored-resume sync hook."""
import io
import os
from unittest.mock import patch

from docx import Document
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


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
    # pypdf extraction may add whitespace differently; just check it picked up something
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


def test_render_text_as_pdf_produces_valid_pdf(app, tmp_path):
    from app.resumes import render_text_as_pdf

    out = tmp_path / "out.pdf"
    with app.app_context():
        render_text_as_pdf("SUMMARY\nA seasoned PM with 8 years of experience.", str(out))
    assert out.exists()
    header = out.read_bytes()[:4]
    assert header == b"%PDF"


def test_generate_tailored_resume_falls_back_to_base_text_without_api_key(app, tmp_path, monkeypatch):
    """No ANTHROPIC_API_KEY → tailor_resume_text returns the base text unchanged."""
    from app.resumes import generate_tailored_resume

    class _Job:
        id = 1
        company = "Acme"
        title = "PM"
        description = "Looking for a PM."

    class _User:
        id = 1

    class _Base:
        extracted_text = "Jordan's base resume content."

    out_dir = tmp_path / "tailored"
    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = ""
        app.config["RESUME_TAILORED_DIR"] = str(out_dir)
        path = generate_tailored_resume(user=_User(), job=_Job(), base_resume=_Base())
    assert path is not None
    assert os.path.exists(path)
    assert open(path, "rb").read()[:4] == b"%PDF"


def test_sync_generates_tailored_resumes_for_new_matches(app, db_session, monkeypatch, tmp_path):
    """The daily sync hook creates one TailoredResume per (user, job) match."""
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
        city_1="New York, NY",
        city_2="Atlanta, GA",
        city_3="Miami, FL",
        city_4="Dallas, TX",
        city_5="Houston, TX",
        city_6="Washington, DC",
    ))
    db_session.add(BaseResume(
        user_id=user.id,
        filename="resume.docx",
        file_path="/tmp/resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extracted_text="Jordan Doe — Senior Product Manager",
    ))
    job = Job(
        source="test",
        company="Acme",
        title="Senior Product Manager",
        normalized_title="senior product manager",
        url="https://example.com/jobs/1",
        city="nyc",
        location="New York, NY",
        description="Looking for a senior PM.",
        is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    saved = db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id).one()
    db_session.add(JobMatch(saved_search_id=saved.id, user_id=user.id, job_id=job.id))
    db_session.commit()
    # Snapshot ids — Flask's teardown_appcontext will close the scoped session
    # below, leaving these instances detached.
    user_id = user.id
    job_id = job.id

    out_dir = tmp_path / "tailored"
    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = ""  # fall back to base text — no network
        app.config["RESUME_TAILORED_DIR"] = str(out_dir)
        created = generate_tailored_resumes()

    assert created == 1
    # Re-open a session through the app's db helper to query the result.
    with app.app_context():
        from app.db import get_db
        fresh = get_db()
        tailored = fresh.query(TailoredResume).filter(
            TailoredResume.user_id == user_id,
            TailoredResume.job_id == job_id,
        ).one()
        assert os.path.exists(tailored.pdf_path)


def test_tailor_resume_text_calls_anthropic_when_key_present(app, monkeypatch):
    """When ANTHROPIC_API_KEY is set, the Anthropic client is called and its
    text response is returned. We mock the SDK so no network happens."""
    from app import resumes as resumes_module

    class _Block:
        type = "text"
        text = "TAILORED OUTPUT"

    class _Message:
        content = [_Block()]

    class _Messages:
        def create(self, **kwargs):
            assert kwargs["model"]  # we passed a model
            assert any("BASE RESUME" in m["content"] for m in kwargs["messages"])
            return _Message()

    class _Client:
        def __init__(self, api_key):
            assert api_key == "sk-test"
            self.messages = _Messages()

    monkeypatch.setattr(resumes_module, "Anthropic", _Client, raising=False)
    # The real import happens inside tailor_resume_text — patch the symbol
    # at module load using sys.modules.
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Client)

    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = "sk-test"
        result = resumes_module.tailor_resume_text(
            base_text="base",
            job_title="PM",
            company="Acme",
            job_description="Looking for a PM.",
        )
    assert result == "TAILORED OUTPUT"
