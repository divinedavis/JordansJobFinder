"""Privacy policy page, its links from every data-collecting form, the
consent-mode default ahead of the Google tag, and that account deletion
removes resume files from disk (the policy promises it)."""
import io
import os

from tests.test_resumes import _make_docx_bytes


def test_privacy_page_renders_and_names_processors(client):
    resp = client.get("/privacy")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Last updated: September 27, 2026" in body
    for name in ("Anthropic", "Stripe", "Cloudflare", "Google", "DigitalOcean"):
        assert name in body


def test_footer_links_privacy_on_every_page(client):
    for path in ("/", "/login", "/sign-in", "/feedback"):
        assert 'href="/privacy"' in client.get(path).get_data(as_text=True), path


def test_data_forms_link_privacy(signed_in_client):
    for path in ("/profile", "/billing"):
        body = signed_in_client.get(path).get_data(as_text=True)
        assert "form-privacy" in body, path


def test_consent_default_precedes_gtag_loader(client):
    body = client.get("/").get_data(as_text=True)
    consent = body.find("gtag('consent', 'default'")
    loader = body.find("googletagmanager.com/gtag/js")
    assert 0 <= consent < loader


def test_account_delete_removes_resume_files(app, signed_in_client, db_session, tmp_path):
    from app.models import BaseResume

    old_tailored = app.config["RESUME_TAILORED_DIR"]
    app.config["RESUME_TAILORED_DIR"] = str(tmp_path / "tailored")
    try:
        signed_in_client.post(
            "/resume/upload",
            data={"resume": (io.BytesIO(_make_docx_bytes("Jordan Doe\nProduct Manager\n")), "r.docx")},
            content_type="multipart/form-data",
        )
        resume = db_session.query(BaseResume).one()
        base_path, uid = resume.file_path, resume.user_id
        user_dir = tmp_path / "tailored" / f"user-{uid}"
        user_dir.mkdir(parents=True)
        (user_dir / "job-1.pdf").write_bytes(b"%PDF-1.4")
        assert os.path.exists(base_path)

        resp = signed_in_client.post("/account/delete")
        assert resp.status_code == 302
        assert not os.path.exists(base_path)
        assert not user_dir.exists()
    finally:
        app.config["RESUME_TAILORED_DIR"] = old_tailored
