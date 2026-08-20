"""Rewrite the document properties of every already-generated tailored resume.

PDFs built before 2026-08-20 carry ReportLab's defaults plus a title reading
"<Company> — Tailored Resume": a per-employer, machine-generated fingerprint
that travels with the file to every recruiter and ATS that opens it. New
renders are clean (see resumes._scrub_pdf_metadata); this fixes the backlog.

Only the metadata is touched — the page content is copied verbatim, because
the AI-tailored text in these files cannot be regenerated without the API.

    python scripts/scrub_resume_metadata.py [--dry-run]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import current_app  # noqa: E402

from app import create_app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.models import BaseResume, TailoredResume, User  # noqa: E402
from app.resumes import _scrub_pdf_metadata, heuristic_structured_parse  # noqa: E402
from app.resumes import _normalize_ligatures  # noqa: E402


def _display_name(db, user_id: int) -> str:
    base = db.query(BaseResume).filter(BaseResume.user_id == user_id).first()
    if base and base.extracted_text:
        user = db.get(User, user_id)
        parsed = heuristic_structured_parse(
            _normalize_ligatures(base.extracted_text),
            user_email=(user.email if user else ""),
        )
        if parsed.get("name"):
            return parsed["name"].title()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db = get_db()
        names: dict[int, str] = {}
        scrubbed = missing = skipped = 0

        def name_for(user_id: int) -> str:
            if user_id not in names:
                names[user_id] = _display_name(db, user_id)
            return names[user_id]

        # Walk the directory, not the DB. There are more PDFs on disk than
        # TailoredResume rows — old rows get pruned and the fallback render
        # deliberately writes a file without recording one — and an orphaned
        # file still carries the fingerprint if it's ever opened or restored.
        targets: dict[str, int] = {}
        for row in db.query(TailoredResume).all():
            if row.pdf_path and os.path.exists(row.pdf_path):
                targets[os.path.abspath(row.pdf_path)] = row.user_id
            else:
                missing += 1
        root = current_app.config["RESUME_TAILORED_DIR"]
        for dirpath, _dirs, files in os.walk(root):
            owner = os.path.basename(dirpath)
            if not owner.startswith("user-"):
                continue
            try:
                user_id = int(owner.split("-", 1)[1])
            except ValueError:
                continue
            for fname in files:
                if fname.lower().endswith(".pdf"):
                    targets.setdefault(os.path.join(dirpath, fname), user_id)

        for path, user_id in sorted(targets.items()):
            name = name_for(user_id)
            title = f"{name} Resume" if name else "Resume"
            if args.dry_run:
                print(f"would scrub {path} -> {title!r}")
            else:
                try:
                    _scrub_pdf_metadata(path, title=title, author=name)
                except Exception as exc:  # noqa: BLE001 - report and continue
                    print(f"SKIP {path}: {exc}")
                    skipped += 1
                    continue
            scrubbed += 1
        print(f"scrubbed={scrubbed} missing_row_file={missing} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
