"""Resume upload, parsing, PDF rendering, and tailored-resume sync hook."""
import io
import json
import os

from docx import Document
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


SAMPLE_STRUCTURED = {
    "name": "Jordan Doe",
    "contact_line_1": "New York, NY | 555-0142 | jordan.doe@example.com",
    "contact_line_2": "linkedin.com/in/jordandoe | jordandoe.dev",
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


def test_resume_management_lives_in_profile(signed_in_client):
    # Resume management moved into the Profile hub; /resume redirects there.
    response = signed_in_client.get("/resume")
    assert response.status_code == 302
    assert "/profile" in response.headers["Location"]
    profile = signed_in_client.get("/profile")
    assert profile.status_code == 200
    assert "base resume" in profile.get_data(as_text=True).lower()


def test_resume_redirects_to_profile(client):
    # /resume always redirects to /profile (which itself gates on auth).
    response = client.get("/resume")
    assert response.status_code == 302
    assert "/profile" in response.headers["Location"]


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
    assert "Jordan Doe" in text
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
    user.set_password("Str0ng-Pass-9x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    db_session.add(SavedSearch(
        user_id=user.id,
        vertical="pm",
        title_slug="technical-product-manager",
        experience_bucket="7-9",
        cities=["New York, NY", "Atlanta, GA", "Miami, FL",
                "Dallas, TX", "Houston, TX", "Washington, DC"],
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
    user.set_password("Str0ng-Pass-9x")
    db_session.add(user); db_session.commit(); db_session.refresh(user)
    db_session.add(SavedSearch(
        user_id=user.id, vertical="pm",
        title_slug="technical-product-manager",
        experience_bucket="7-9",
        cities=["New York, NY", "Atlanta, GA", "Miami, FL",
                "Dallas, TX", "Houston, TX", "Washington, DC"],
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
    assert result["name"] == "Jordan Doe"
    assert result["experience"][0]["company"] == "JPMorgan Chase"


def test_tailor_resume_structured_tolerates_trailing_prose(app, monkeypatch):
    """Anthropic sometimes appends a closing sentence after the JSON.
    raw_decode must consume only the first JSON object and ignore the rest."""
    from app import resumes as resumes_module

    class _Block:
        type = "text"
        text = json.dumps(SAMPLE_STRUCTURED) + "\n\nLet me know if you want any tweaks."

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
    assert result["name"] == "Jordan Doe"


def test_tailor_resume_structured_tolerates_leading_prose(app, monkeypatch):
    """And sometimes prepends 'Here is the resume:' before the JSON."""
    from app import resumes as resumes_module

    class _Block:
        type = "text"
        text = "Here is the tailored resume:\n\n" + json.dumps(SAMPLE_STRUCTURED)

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
    assert result["name"] == "Jordan Doe"


def _seed_match_for_signed_in_user(db_session, with_base_resume=True):
    """Give the signed-in test user a base resume + one PM JobMatch."""
    from app.models import BaseResume, Job, JobMatch, SavedSearch, User

    user = db_session.query(User).first()
    if with_base_resume:
        db_session.add(BaseResume(
            user_id=user.id, filename="resume.docx", file_path="/tmp/resume.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            extracted_text="Jordan Doe — Senior Product Manager",
        ))
    job = Job(
        source="test", company="Acme", title="Senior Product Manager",
        normalized_title="senior product manager",
        url="https://example.com/jobs/ondemand", city="nyc", location="New York, NY",
        description="We need a product manager with 8 years of experience.",
        vertical="pm", is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    saved = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    db_session.add(JobMatch(saved_search_id=saved.id, user_id=user.id, job_id=job.id))
    db_session.commit()
    # Return primitive ids — the ORM objects detach once a request closes the
    # session, so callers that assert after a request must use ids.
    return user.id, job.id


def test_dashboard_shows_tailored_button_when_user_has_base_resume(signed_in_client, db_session):
    """The button must appear for every match once a base resume exists, even
    before the nightly sync has pre-built any tailored PDFs."""
    _seed_match_for_signed_in_user(db_session, with_base_resume=True)
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "Tailored Resume" in body


def test_dashboard_hides_tailored_button_without_base_resume(signed_in_client, db_session):
    """No base resume → no tailored button (nothing to tailor from)."""
    _seed_match_for_signed_in_user(db_session, with_base_resume=False)
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "Tailored Resume" not in body


def test_tailored_download_generates_on_demand(signed_in_client, db_session, monkeypatch, tmp_path):
    """Clicking the button generates + serves a tailored PDF on demand (and
    persists the row) when the nightly sync hasn't pre-built it."""
    from app.models import TailoredResume

    user_id, job_id = _seed_match_for_signed_in_user(db_session, with_base_resume=True)

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

    app = signed_in_client.application
    app.config["ANTHROPIC_API_KEY"] = "sk-test"
    app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")

    response = signed_in_client.get(f"/resume/tailored/{job_id}")
    assert response.status_code == 200
    assert response.data[:4] == b"%PDF"

    row = db_session.query(TailoredResume).filter(
        TailoredResume.user_id == user_id, TailoredResume.job_id == job_id
    ).one()
    assert os.path.exists(row.pdf_path)


def test_tailored_download_without_base_resume_sends_user_to_profile(signed_in_client, db_session):
    """No base resume and no pre-built PDF → a redirect with an explanation,
    not the bare Werkzeug 404 the button used to land on."""
    _user_id, job_id = _seed_match_for_signed_in_user(db_session, with_base_resume=False)
    response = signed_in_client.get(f"/resume/tailored/{job_id}")
    assert response.status_code == 302
    assert "/profile" in response.headers["Location"]


def _break_anthropic(monkeypatch):
    """Make every Anthropic call raise the way an empty credit balance does."""
    class _Messages:
        def create(self, **kw):
            raise RuntimeError(
                "Error code: 400 - Your credit balance is too low to access the "
                "Anthropic API."
            )

    class _Client:
        def __init__(self, api_key):
            self.messages = _Messages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Client)


def test_tailored_download_falls_back_when_the_api_fails(
    signed_in_client, db_session, monkeypatch, tmp_path
):
    """2026-08-20: the Anthropic balance ran out, the 400 escaped
    tailor_resume_structured, and the dashboard's Tailored Resume button
    returned a bare 404. The documented fallback never ran because it only
    triggers on None. Now the styled base resume is served instead, the
    AI-resume credit spent up front is refunded, and NO TailoredResume row is
    written — otherwise the un-tailored PDF would be served forever once the
    API came back."""
    from app.models import Subscription, TailoredResume

    user_id, job_id = _seed_match_for_signed_in_user(db_session, with_base_resume=True)
    _break_anthropic(monkeypatch)

    app = signed_in_client.application
    app.config["ANTHROPIC_API_KEY"] = "sk-test"
    app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")

    response = signed_in_client.get(f"/resume/tailored/{job_id}")
    assert response.status_code == 200
    assert response.data[:4] == b"%PDF"

    assert db_session.query(TailoredResume).filter(
        TailoredResume.user_id == user_id, TailoredResume.job_id == job_id
    ).count() == 0

    sub = db_session.query(Subscription).filter(
        Subscription.user_id == user_id
    ).one_or_none()
    assert sub is None or sub.resume_credits_used == 0


def test_tailor_resume_structured_returns_none_on_api_error(app, monkeypatch):
    """The API call is wrapped: a billing/network/rate-limit failure returns
    None so the caller can fall back, instead of raising."""
    from app.resumes import tailor_resume_structured

    _break_anthropic(monkeypatch)
    with app.app_context():
        app.config["ANTHROPIC_API_KEY"] = "sk-test"
        assert tailor_resume_structured(
            base_text="Jordan Doe — Senior Product Manager",
            job_title="Senior Product Manager",
            company="Acme",
            job_description="We need a PM.",
        ) is None


def test_refund_resume_credit_never_goes_negative(signed_in_client, db_session):
    """A double refund must not drive the counter below zero — that would hand
    out free AI-resume creations."""
    from app.models import Subscription, User
    from app.payments import refund_resume_credit

    user = db_session.query(User).first()
    sub = db_session.query(Subscription).filter(
        Subscription.user_id == user.id
    ).one_or_none()
    if sub is None:
        sub = Subscription(user_id=user.id, status="free")
        db_session.add(sub)
    sub.resume_credits_used = 1
    db_session.commit()

    refund_resume_credit(sub)
    assert sub.resume_credits_used == 0
    refund_resume_credit(sub)
    assert sub.resume_credits_used == 0


def test_experience_renders_without_table_flowables(app):
    """2026-09-01: experience used a two-column Table with the dates in a
    right-aligned cell. Text extractors read that wide gap as a column break
    and parsed each side separately, so Workday's autofill built one dateless
    work-experience record per date range and filled in no title or employer.
    Supersedes the old hAlign regression — the tables are gone entirely."""
    from reportlab.platypus import KeepTogether, Paragraph, Table
    from app.resumes import _competencies_block, _experience_block, _styles

    with app.app_context():
        styles = _styles()
        data = {
            "experience": [{
                "company": "JPMorgan Chase & Co.",
                "location": "New York, NY",
                "dates": "2022 – Present",
                "roles": [{"title": "Vice President", "dates": "2022 – Present",
                           "bullets": ["Did things."]}],
            }],
            "competencies": [{"label": "Strategy", "items": "Roadmaps, OKRs"}],
        }
        blocks = _experience_block(data, styles) + _competencies_block(data, styles)

    def _flat(flowables):
        for f in flowables:
            if isinstance(f, KeepTogether):
                yield from _flat(getattr(f, "_content", []) or [])
            else:
                yield f

    flat = list(_flat(blocks))
    assert not [f for f in flat if isinstance(f, Table)], "no tables in a parseable resume"
    lines = [f.text for f in flat if isinstance(f, Paragraph)]
    # The employer heading carries its location and NO date range — a dated
    # company row was read as an extra, titleless job.
    assert "JPMorgan Chase &amp; Co. | New York, NY" in lines
    assert not any("Chase" in ln and "2022" in ln and "Vice President" not in ln for ln in lines)
    # The role line is a bold title flush left with the dates flush right,
    # drawn as one flowable; the employer heads the block and is not
    # repeated (2026-09-03).
    from app.resumes import _RoleLine
    roles = [f for f in flat if isinstance(f, _RoleLine)]
    assert [(r.title, r.dates) for r in roles] == [("Vice President", "2022 – Present")]


def test_competencies_render_as_bold_labelled_bullets(app):
    """2026-08-20: competencies used to be a two-column table, which forced
    long labels to wrap in a narrow gutter. The candidate's own resume runs
    them as bullets — "**Label:** items" on one flowing line — so the label
    can't collide with its items no matter how long it is."""
    from reportlab.platypus import Paragraph
    from app.resumes import _competencies_block, _styles

    with app.app_context():
        blocks = _competencies_block(
            {"competencies": [
                {"label": "Technical Domain Expertise", "items": "AWS, APIs."},
                {"label": "", "items": "Unlabelled row still renders."},
            ]},
            _styles(),
        )
    paragraphs = [b for b in blocks if isinstance(b, Paragraph)]
    # Heading + one paragraph per row.
    assert len(paragraphs) == 3
    assert "<b>Technical Domain Expertise:</b>" in paragraphs[1].text
    # The marker is part of the TEXT, not reportlab's bulletText, so it lands
    # in the PDF's text layer where a resume parser can see it.
    assert all(p.text.startswith("\u00b7 ") for p in paragraphs[1:])
    assert all(not p.bulletText for p in paragraphs[1:])


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


def test_clicking_tailored_resume_marks_match_applied(signed_in_client, db_session, app, tmp_path):
    """Downloading the tailored resume stamps applied_at on the user's JobMatch
    (drives the green 'Applied' badge) and load_db_matches exposes it."""
    from app.models import BaseResume, Job, JobMatch, SavedSearch, User
    from app.results import load_db_matches

    user = db_session.query(User).first()
    db_session.add(BaseResume(
        user_id=user.id, filename="resume.docx", file_path="/tmp/resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extracted_text="Jordan Doe — Senior Product Manager. Experience: led platform teams.",
    ))
    job = Job(
        source="test", company="Acme", title="Senior Product Manager",
        normalized_title="senior product manager",
        url="https://example.com/jobs/applied-1", city="nyc", location="New York, NY",
        description="Looking for a senior PM.", is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(job)
    saved = db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id).first()
    assert saved is not None, "signed-up user should have an auto-seeded saved search"
    db_session.add(JobMatch(saved_search_id=saved.id, user_id=user.id, job_id=job.id))
    db_session.commit()
    job_id, user_id = job.id, user.id

    app.config["ANTHROPIC_API_KEY"] = ""
    app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")

    # Before the click: not applied.
    with app.app_context():
        before = [m for m in load_db_matches(saved) if m["id"] == job_id]
        assert before and before[0]["applied"] is False

    resp = signed_in_client.get(f"/resume/tailored/{job_id}")
    assert resp.status_code == 200

    with app.app_context():
        from app.db import get_db
        fresh = get_db()
        jm = fresh.query(JobMatch).filter(
            JobMatch.user_id == user_id, JobMatch.job_id == job_id
        ).first()
        assert jm.applied_at is not None
        saved = fresh.query(SavedSearch).filter(SavedSearch.user_id == user_id).first()
        after = [m for m in load_db_matches(saved) if m["id"] == job_id]
        assert after and after[0]["applied"] is True


def test_normalize_ligatures_repairs_pdf_extraction_damage():
    """2026-08-20: the black squares in the rendered resume were real Unicode
    ligature codepoints (U+FB01 …) that Helvetica can't encode — not the
    "■" spellings the old fix table was written against, so none of them ever
    matched. The same PDF also decodes "ti" as "<" in the body font and as "A"
    in the bold one."""
    from app.resumes import _normalize_ligatures

    src = (
        "high-net-worth \ufb01nancial services, opera\u003conal e\ufb03ciency, "
        "Con\ufb02uence, Cla\ufb02in University, support <ckets, multiple <me "
        "zones, Change & AdopAon, AnalyAcs & ReporAng, h=p://example.com, "
        "plaPorm moderniza<on"
    )
    fixed = _normalize_ligatures(src)
    for expected in (
        "financial", "operational", "efficiency", "Confluence", "Claflin",
        "support tickets", "multiple time zones", "Adoption", "Analytics",
        "Reporting", "http://example.com", "platform modernization",
    ):
        assert expected in fixed, (expected, fixed)
    assert "<" not in fixed
    assert not any(c in fixed for c in "\ufb01\ufb02\ufb03")


def test_normalize_ligatures_leaves_clean_text_alone():
    """The "A means ti" repair only runs on a document already proven broken —
    otherwise it would turn iPhone into itfhone and PayPal into gibberish."""
    from app.resumes import _normalize_ligatures

    clean = "Shipped iPhone and iPad apps; PayPal and eBay integrations."
    assert _normalize_ligatures(clean) == clean


def test_renderable_never_leaves_a_black_box():
    """Anything outside the base-14 font's WinAnsi encoding is folded to ASCII
    or dropped. A codepoint that reaches ReportLab unencodable is drawn as a
    solid black square in the middle of a sentence."""
    from app.resumes import _renderable

    assert _renderable("e\ufb03cient \ufb01nance") == "efficient finance"
    # cp1252 characters survive untouched (em dash, bullet, accented letters).
    assert _renderable("caf\u00e9 \u2014 r\u00e9sum\u00e9 \u2022 item") == (
        "caf\u00e9 \u2014 r\u00e9sum\u00e9 \u2022 item"
    )
    # Outside cp1252 with no ASCII form → dropped, not boxed.
    assert "\u2192" not in _renderable("before \u2192 after")


def test_rendered_pdf_carries_no_generator_fingerprint(app, tmp_path):
    """No "<Company> — Tailored Resume" title, no "(anonymous)" author, no
    ReportLab producer string. The document properties travel with the file to
    every recruiter and ATS that opens it."""
    from pypdf import PdfReader
    from app.resumes import render_resume_pdf

    out = tmp_path / "resume.pdf"
    with app.app_context():
        render_resume_pdf(SAMPLE_STRUCTURED, str(out))
    meta = PdfReader(str(out)).metadata
    blob = " ".join(str(v) for v in meta.values()).lower()
    for banned in ("tailored", "anonymous", "unspecified", "reportlab"):
        assert banned not in blob, (banned, dict(meta))
    assert meta["/Title"] == "Jordan Doe Resume"
    assert meta["/Author"] == "Jordan Doe"


def test_heuristic_header_stops_at_the_headline():
    """"Jordan Doe Senior Product Manager | Private Wealth Management" is a
    name plus a title — the header used to print all four words as the name,
    and the leftover "| jordandoe.dev (portfolio)" opened the summary."""
    from app.resumes import heuristic_structured_parse

    text = (
        "Jordan Doe Senior Product Manager | Private Wealth Management & AI "
        "Transformation http://www.linkedin.com/in/jordandoe | Mobile: "
        "555-555-0142| jordan.doe@example.com | jordandoe.dev (portfolio)    "
        "Strategic Product Manager with 10 years of experience in financial "
        "services."
    )
    parsed = heuristic_structured_parse(text, user_email="jordan.doe@example.com")
    assert parsed["name"] == "Jordan Doe"
    assert parsed["summary"].startswith("Strategic Product Manager")
    # The portfolio domain belongs on the contact line, not in the summary.
    # One line, ordered like the candidate's resume: profile, phone, email, site.
    assert "jordandoe.dev" in parsed["contact_line_1"]
    assert parsed["contact_line_1"].startswith("http://www.linkedin.com/in/jordandoe")
    assert "Mobile: 555-555-0142" in parsed["contact_line_1"]
    assert "jordandoe.dev" not in parsed["summary"]
    assert parsed["headline"] == "Senior Product Manager | Private Wealth Management & AI Transformation"


def test_renderable_strips_invisible_characters():
    """Nothing unprintable survives into a rendered document. A soft hyphen and
    a non-breaking space both encode in cp1252, so the encoding filter alone
    would pass them through — and an invisible character wedged inside a word
    is both the shape a hidden marker takes and a reliable way to break ATS
    keyword matching."""
    from app.resumes import _renderable

    assert _renderable("prod­uct man​ager") == "product manager"
    assert _renderable("Senior Product Manager") == "Senior Product Manager"
    for zero_width in ("​", "‌", "‍", "⁠", "﻿", "‮"):
        assert zero_width not in _renderable(f"a{zero_width}b")
    assert _renderable("a​b") == "ab"


def test_layout_matches_the_candidates_own_resume(app, tmp_path):
    """2026-08-20: the generated PDF is laid out like the candidate's own Word
    resume — name over a headline over one contact line, a rule, the summary,
    then CORE COMPETENCIES before PROFESSIONAL EXPERIENCE, and EDUCATION and
    SOFTWARE & TOOLS as their own sections. One employer with two roles prints
    ONE company heading with two dated titles under it."""
    from pypdf import PdfReader
    from app.resumes import render_resume_pdf

    data = {
        "name": "Jordan Doe",
        "headline": "Senior Product Manager | Platform Modernization",
        "contact_line_1": "linkedin.com/in/jordandoe | Mobile: 555-0142 | jordan.doe@example.com",
        "summary": "Ten years shipping platforms.",
        "experience": [{
            "company": "Acme Bank",
            "dates": "August 2021 - Present",
            "roles": [
                {"title": "Vice President", "dates": "January 2024 - Present",
                 "bullets": ["Led the migration."]},
                {"title": "Senior Associate", "dates": "August 2021 - January 2024",
                 "bullets": ["Ran delivery."]},
            ],
        }],
        "competencies": [{"label": "Delivery", "items": "Agile, Scrum."}],
        "education": [{"school": "State University", "degree": "B.S. Computer Science",
                       "dates": "May 2016"}],
        "tools": "Jira, Confluence",
    }
    out = tmp_path / "resume.pdf"
    with app.app_context():
        render_resume_pdf(data, str(out))
    text = "".join(p.extract_text() for p in PdfReader(str(out)).pages)

    for expected in (
        "Jordan Doe", "Senior Product Manager | Platform Modernization",
        "CORE COMPETENCIES:", "PROFESSIONAL EXPERIENCE:",
        "EDUCATION & CERTIFICATION:", "SOFTWARE & TOOLS:",
        "Acme Bank", "Vice President", "Senior Associate",
        "State University | B.S. Computer Science | May 2016",
        "Jira, Confluence",
    ):
        assert expected in text, expected
    # The employer heads its roles once; role lines don't repeat it.
    assert text.count("Acme Bank") == 1
    # Competencies come before experience, the way the candidate's resume runs.
    assert text.index("CORE COMPETENCIES:") < text.index("PROFESSIONAL EXPERIENCE:")


def test_contact_links_are_clickable_and_rewritten(app, tmp_path):
    """Portfolio domains are rewritten to the URL the candidate wants used, and
    every link-shaped fragment becomes a real PDF link — a plain-text URL on a
    resume is a URL nobody clicks."""
    from pypdf import PdfReader
    from app.resumes import _sanitize_structured, render_resume_pdf

    app.config["RESUME_LINK_REWRITES"] = '{"jordandoe.dev": "https://jordandoe.dev/portfolio.html"}'
    with app.app_context():
        clean = _sanitize_structured({
            "name": "Jordan Doe",
            "contact_line_1": "linkedin.com/in/jordandoe | Mobile: 555-0142 | jordandoe.dev",
        })
        assert "https://jordandoe.dev/portfolio.html" in clean["contact_line_1"]
        # An already-correct URL isn't rewritten into itself.
        again = _sanitize_structured(
            {"contact_line_1": "https://jordandoe.dev/portfolio.html"}
        )
        assert again["contact_line_1"] == "https://jordandoe.dev/portfolio.html"

        out = tmp_path / "links.pdf"
        render_resume_pdf(clean, str(out))
    annots = PdfReader(str(out)).pages[0].get("/Annots") or []
    hrefs = {str(a.get_object()["/A"]["/URI"]) for a in annots}
    assert "https://jordandoe.dev/portfolio.html" in hrefs
    assert any(h.startswith("https://linkedin.com/in/") for h in hrefs)
    # The phone number is not a link.
    assert not any("555-0142" in h for h in hrefs)


def test_heuristic_splits_roles_from_bullets_and_employers():
    """Two-column extraction flattens "company  dates / title  dates / bullets"
    into one run, which used to print the job title as the first bullet point
    and file every later employer under the first one."""
    from app.resumes import heuristic_structured_parse

    text = (
        "Jordan Doe Senior Product Manager | Platforms "
        "linkedin.com/in/jordandoe | 555-0142 | jordan.doe@example.com "
        "Summary: Ten years shipping platforms. "
        "Professional Experience: Acme Bank August 2021 - Present "
        "Vice President, Product January 2024 - Present "
        "• Led the AWS migration for 50 applications. "
        "• Cut latency by 20%. Senior Associate, Product "
        "August 2021 - January 2024 "
        "• Ran modernization delivery. Globex Industries. "
        "November 2016 - August 2021 • Technical Program Manager. "
        "January 2018 - August 2021 • Managed three integrations."
    )
    parsed = heuristic_structured_parse(text, user_email="jordan.doe@example.com")
    companies = [e["company"] for e in parsed["experience"]]
    assert "Acme Bank" in companies
    assert "Globex Industries" in companies
    acme = parsed["experience"][companies.index("Acme Bank")]
    titles = [r["title"] for r in acme["roles"]]
    assert "Vice President, Product" in titles
    assert "Senior Associate, Product" in titles
    # The title must not survive as a bullet point.
    assert all(
        "Vice President" not in b for r in acme["roles"] for b in r["bullets"]
    )


def test_a_long_role_does_not_swallow_the_next_roles_title():
    """2026-09-01: the bullet extractor capped at 8 BEFORE the next role's
    title was peeled off the tail of the last bullet, so a role with nine or
    more bullets silently dropped both that bullet and the title of the role
    beneath it — "Senior Associate, Technical Program Manager" vanished from
    the rendered resume."""
    from app.resumes import heuristic_structured_parse

    bullets = " ".join(
        f"\u2022 Delivered platform initiative number {n} on schedule."
        for n in range(1, 10)
    )
    text = (
        "Jordan Doe Senior Product Manager | Platforms "
        "linkedin.com/in/jordandoe | 555-0142 | jordan.doe@example.com "
        "Summary: Ten years shipping platforms. "
        "Professional Experience: Acme Bank August 2021 - Present "
        "Vice President, Product January 2024 - Present "
        f"{bullets} Senior Associate, Product "
        "August 2021 - January 2024 "
        "\u2022 Ran modernization delivery."
    )
    parsed = heuristic_structured_parse(text, user_email="jordan.doe@example.com")
    acme = parsed["experience"][0]
    assert acme["company"] == "Acme Bank"
    titles = [r["title"] for r in acme["roles"]]
    assert titles == ["Vice President, Product", "Senior Associate, Product"]
    # The ninth bullet is the user's own content and must survive too.
    assert len(acme["roles"][0]["bullets"]) == 9


def test_rendered_pdf_is_parseable_by_an_ats(app, tmp_path):
    """2026-09-01: Workday's "Autofill with Resume" turned four jobs into six
    work-experience records, every one of them with a date range but no job
    title and no company, and no role description at all.

    The text layer is the whole contract with an ATS, so assert on it: one
    line per role carrying title + employer + dates, no dated employer row to
    spawn a phantom job, education split on a real delimiter, and bullet
    markers that actually survive extraction."""
    from pypdf import PdfReader
    from app.resumes import render_resume_pdf

    data = {
        "name": "Jordan Doe",
        "headline": "Senior Product Manager",
        "contact_line_1": "jordan.doe@example.com",
        "summary": "Ten years shipping platforms.",
        "experience": [{
            "company": "Acme Bank",
            "location": "New York, NY",
            "dates": "August 2021 - Present",
            "roles": [
                {"title": "Vice President", "dates": "January 2024 - Present",
                 "bullets": ["Led the migration."]},
                {"title": "Senior Associate", "dates": "August 2021 - January 2024",
                 "bullets": ["Ran delivery."]},
            ],
        }],
        "competencies": [{"label": "Delivery", "items": "Agile, Scrum."}],
        "education": [{"school": "State University", "degree": "B.S. Computer Science",
                       "dates": "May 2016"}],
        "tools": "Jira, Confluence",
    }
    out = tmp_path / "ats.pdf"
    with app.app_context():
        render_resume_pdf(data, str(out))
    pages = PdfReader(str(out)).pages
    lines = [
        ln.strip()
        for p in pages
        for ln in (p.extract_text(extraction_mode="layout") or "").splitlines()
        if ln.strip()
    ]

    def line_with(*needles):
        return [ln for ln in lines if all(n in ln for n in needles)]

    # Each role is one line holding its title AND its dates, not a title in
    # one column and a date in another.
    assert line_with("Vice President", "January 2024 - Present")
    assert line_with("Senior Associate", "August 2021 - January 2024")
    # The employer heads the block, on its own dateless line right above.
    assert line_with("Acme Bank", "New York, NY")
    # No dated employer row: the ONLY line holding the employer's own span also
    # names the role that span belongs to.
    for ln in line_with("August 2021 - Present"):
        assert "Senior Associate" in ln or "Vice President" in ln, ln
    # A resume parser splits on the delimiter, so it must not be glued to a word.
    assert line_with("State University | B.S. Computer Science | May 2016")
    # Bullet markers reach the text layer.
    text = "".join(p.extract_text() or "" for p in pages)
    assert text.count("\u00b7") >= 3, "bullet markers must survive extraction"
    # U+2022 comes back as a DEL control char from a base-14 font. Nothing in
    # the text layer may be a control character.
    assert not [c for c in text if ord(c) < 32 and c not in "\n\r\t"]
    assert "\x7f" not in text
    # The ONLY wide gaps in the text layer are the role lines' right-aligned
    # dates — the owner's call (2026-09-03), matching their own Word resume.
    # Everything else stays gap-free so no other line can read as a table.
    role_dates = ("January 2024 - Present", "August 2021 - January 2024")
    gappy = [ln for ln in lines if "      " in ln.strip()]
    assert gappy, "role dates should be flush right"
    for ln in gappy:
        assert any(d in ln for d in role_dates), f"column gap outside a role line: {ln!r}"


def test_employer_location_is_split_out_for_the_ats_location_field():
    """Workday asks for a Location per work experience. Pull "City, ST" off the
    employer line when it's there, and leave an employer whose own name has a
    comma in it alone."""
    from app.resumes import _split_company_location, heuristic_structured_parse

    assert _split_company_location("Acme Bank | New York, NY") == ("Acme Bank", "New York, NY")
    assert _split_company_location("Acme Bank, Lancaster, PA") == ("Acme Bank", "Lancaster, PA")
    assert _split_company_location("Acme Bank \u2013 London, England") == ("Acme Bank", "London, England")
    # Not a place: an employer name that merely ends in a comma-phrase.
    assert _split_company_location("Smith, Kline and Co") == ("Smith, Kline and Co", "")
    assert _split_company_location("Acme Bank") == ("Acme Bank", "")

    text = (
        "Jordan Doe jordan.doe@example.com "
        "Professional Experience: Acme Bank | New York, NY August 2021 - Present "
        "Vice President, Product January 2024 - Present "
        "\u2022 Led the migration."
    )
    parsed = heuristic_structured_parse(text, user_email="jordan.doe@example.com")
    assert parsed["experience"][0]["company"] == "Acme Bank"
    assert parsed["experience"][0]["location"] == "New York, NY"


def test_resume_regexes_do_not_blow_up_on_hostile_text():
    """Every one of these patterns runs over text lifted out of an UPLOADED
    resume. A nested quantifier against a $ anchor is a denial-of-service knob
    a stranger can turn with one crafted PDF, so they're all bounded."""
    import time
    from app.resumes import (
        _contact_markup, _normalize_ligatures, _peel_company, _peel_role_title,
        _split_company_location,
    )

    bomb = "Word. " + ("Aa " * 4_000) + "Manager"
    started = time.monotonic()
    _peel_role_title([bomb])
    _peel_company([bomb])
    _split_company_location(bomb)
    _contact_markup(("a." * 3_000) + "com | " + ("b" * 5_000))
    _normalize_ligatures(bomb)
    assert time.monotonic() - started < 5


def test_dashboard_warns_before_the_click_when_tailoring_is_down(
    signed_in_client, db_session, monkeypatch, tmp_path
):
    """2026-08-20: the only warning was a flash shown AFTER the download, so an
    untailored resume read as a broken template rather than an outage. The
    board now says so up front, and stops saying it once a call succeeds."""
    from app import resumes as resumes_module

    app = signed_in_client.application
    app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")
    _seed_match_for_signed_in_user(db_session, with_base_resume=True)

    with app.app_context():
        resumes_module.clear_ai_failure()
    assert "Tailoring is paused" not in signed_in_client.get("/dashboard").get_data(as_text=True)

    with app.app_context():
        resumes_module.record_ai_failure("The test API has no credit balance")
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "Tailoring is paused" in body
    assert "no credit balance" in body

    with app.app_context():
        resumes_module.clear_ai_failure()
    assert "Tailoring is paused" not in signed_in_client.get("/dashboard").get_data(as_text=True)


def test_ai_failure_marker_goes_stale(app, tmp_path):
    """A day-old failure stops nagging: nothing has tried since, and the API may
    well be back."""
    import json
    import os
    from datetime import datetime, timedelta, timezone
    from app import resumes as resumes_module

    app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")
    with app.app_context():
        resumes_module.record_ai_failure("down")
        assert resumes_module.ai_tailoring_status()["available"] is False
        path = resumes_module._ai_status_path()
        stale = datetime.now(timezone.utc) - timedelta(
            hours=resumes_module.AI_FAILURE_TTL_HOURS + 1
        )
        with open(path, "w") as fh:
            json.dump({"failed_at": stale.isoformat(), "reason": "down"}, fh)
        assert resumes_module.ai_tailoring_status()["available"] is True
        os.remove(path)


def test_role_line_puts_dates_flush_right_and_falls_back_inline(app):
    """2026-09-03: the owner couldn't tell a role line from the bullets under
    it and wants the dates flush right, as on their own Word resume. The
    title prints bold, the dates right-aligned on the same baseline. A title
    too long to share the line falls back to the inline **Title** | Dates
    paragraph — and to regular weight if even bold would wrap the dates onto
    their own line (the Workday phantom-job bug)."""
    from reportlab.platypus import Paragraph
    from app.resumes import _RoleLine, _role_line, _role_paragraph, _styles

    styles = _styles()
    title = "Vice President, Technical Program and Product Manager"
    line = _role_line(title, "January 2024 - Present", styles)
    assert isinstance(line, _RoleLine)
    assert (line.title, line.dates) == (title, "January 2024 - Present")
    assert line.bold_font == "Helvetica-Bold" and line.regular_font == "Helvetica"
    assert line.wrap(504, 10_000)[1] == styles["role"].leading

    # Too long for one line with a right-aligned date: inline fallback.
    long_title = ("Vice President, Technical Program, Product, Portfolio and "
                  "Platform Delivery Manager")
    fallback = _role_line(long_title, "January 2024 - Present", styles, avail_width=480)
    assert isinstance(fallback, Paragraph)
    assert fallback.text.startswith(f"<b>{long_title}</b> | ") or fallback.text.startswith(long_title + " | ")

    # The inline fallback drops bold rather than let the dates wrap.
    para = _role_paragraph(long_title, "January 2024 - Present", styles, avail_width=480)
    assert "<b>" not in para.text, para.text
    assert para.text.startswith(long_title + " | ")
    # No dates at all: just the bold title.
    only = _role_line("Technical Program Manager", "", styles)
    assert isinstance(only, Paragraph) and only.text == "<b>Technical Program Manager</b>"
