# Jordan's Job Finder

## What This App Does

A Flask web app + daily scraper that finds technical **Product Manager** and **Program Manager** jobs for Jordan across 6 metros (NYC, Atlanta, Miami, Dallas, Houston, DC). It scrapes 340+ company career pages daily and surfaces matches based on role, seniority, location, salary, and tech focus.

**Live at:** https://jordansjobfinder.com
**Server:** 159.203.110.79 (DigitalOcean)
**Path:** /var/www/jordansjobfinder
**Repo:** https://github.com/divinedavis/JordansJobFinder.git (branch: master)

## Architecture

- **Web framework:** Flask + Jinja2 (app/__init__.py, routes.py, wsgi.py)
- **Database:** SQLAlchemy with SQLite (db.py, models.py) at jordansjobfinder.db
- **Scraper:** scraper.py — Requests, BeautifulSoup, Playwright
- **Matching:** matching.py, parsing.py, catalog.py — regex-based experience/title/salary parsing
- **Billing:** payments.py — Stripe (scaffolded, not yet connected)
- **Auth:** routes.py — email/password (pbkdf2:sha256)
- **Deploy:** deploy/ — Gunicorn (port 8100), systemd, Nginx reverse proxy

## Cron Schedule (America/New_York)

- **5:00 AM ET** — scraper.py runs (~40 min), scrapes all ATS platforms, writes shared_jobs.json
- **6:00 AM ET** — manage.py run-daily-sync imports shared_jobs.json into DB, rebuilds user matches

## Scraper Pipeline (scraper.py)

Scrapes 5 ATS platforms: Workday (~246 entries), Greenhouse (~86), Lever (~7), Eightfold (~2), custom Playwright (JPMorgan, Goldman, MetLife, Google, Meta, Amazon). Entry counts are company×city tuples — many companies appear in multiple cities.

Filter chain for each job:
1. **Role** — title contains "product manager" or "program manager"
2. **Seniority** — every city accepts VP or Senior/Lead/Staff/Principal titles (plain Director/Manager titles still excluded)
3. **Location** — must be in one of the 6 metros (NYC, Atlanta, Miami, Dallas, Houston, DC)
4. **Recency** — posted within last 2 days
5. **Salary** — $180K+ floor (capped at $2M to filter garbage numbers from page HTML); enforced for NYC only — all other cities are salary-optional (SALARY_OPTIONAL_CITIES)
6. **Tech focus** — 3+ tech keywords in description (agile, cloud, API, etc.)

Outputs: jobs.html (static public board), jobs_store.json, shared_jobs.json, seen_jobs.json

## Finance + Sales Verticals (scraper_finance.py, scraper_sales.py)

Two sibling scrapers surface **entry-level finance** and **entry-level sales**
roles across all 11 metros (the 6 above plus York-PA, Lancaster-PA,
Philadelphia-PA, Harrisburg-PA, Baltimore-MD). Each writes its own
`shared_jobs_finance.json` / `shared_jobs_sales.json`, tagged with a `vertical`
field, which `app/sync.py` ingests alongside `shared_jobs.json`. Both run in the
9 AM cron chain after `scraper.py`. Filter chain: entry-level title keywords
(no senior/manager/VP) → location in one of the 11 metros (`infer_city` /
`CITY_LOCATION_PATTERNS`) → posted within 2 days (unknown dates are dropped).

Native platforms: **Workday** (`*_WORKDAY_COMPANIES`) + **Greenhouse**
(`*_GREENHOUSE_COMPANIES`), plus Citi RSS and Playwright (JPMorgan/Goldman) in
finance.

### Extra ATS platforms (scraper_ats_extra.py)

The big national employers are on Workday/Greenhouse, but the **regional** PA/MD
employers (Armstrong, WellSpan, Fulton Bank, Dentsply, Hershey, …) are not.
`scraper_ats_extra.py` adds five more platforms and both verticals call its
`collect_extra_jobs()` (passing their own `title_filter` / `infer_city` /
`within_recency` / `make_job`, so the platform logic lives here and the vertical
logic stays in each caller):

- **Oracle Cloud Recruiting** (JSON) — WellSpan/York, Penn National/Harrisburg
- **Lever** (JSON) — Gopuff/Philly
- **Phenom** (JSON) — DISABLED: Exelon/Constellation 403 the droplet IP (WAF)
- **iCIMS** (HTML, needs `&in_iframe=1`) — Fulton Bank/Lancaster, Graham Packaging/York
- **SuccessFactors** CSB (HTML, `tr.data-row`) — Armstrong/Lancaster, Dentsply & Voith/York, Hershey/Harrisburg, McCormick/Baltimore

Notes: iCIMS list pages and Voith/McCormick SF pages carry no date, so the date
is pulled from the detail page (only for title+city survivors). SF boards are
newest-first → dated sites early-stop; undated sites are bounded by
`MAX_SF_PAGES`. Each company is isolated in `_safe()` so one failure/timeout
doesn't sink the run. **York/Lancaster have no dedicated local employer on
Workday/Greenhouse — these HTML/JSON platforms are the only way to reach them.**

### Probe recipe before adding a company

Never add an endpoint that doesn't return HTTP 200 from the **production droplet
IP** (some WAFs, e.g. Phenom, allow residential IPs but block datacenters).
Verify from the server:
- **Workday**: `POST https://{tenant}.wd{ver}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` with `{"appliedFacets":{},"limit":1,"offset":0,"searchText":"analyst"}`.
- **Greenhouse**: `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs`.
- **Oracle**: `GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber={CX_n},limit=1` (siteNumber is `CX_1` or `CX` — varies).
- **Lever**: `GET https://api.lever.co/v0/postings/{handle}?mode=json`.
- **iCIMS**: `GET https://{sub}.icims.com/jobs/search?ss=1&hashed=-1&in_iframe=1` (browser UA; the `in_iframe=1` is mandatory).
- **SuccessFactors**: `GET https://{careers-host}/search/?q=&startrow=0` (browser UA; parse `tr.data-row`).

## Database Models

- **User** — email, password hash
- **MagicLinkToken** — scaffolded, not active
- **Subscription** — Stripe customer/subscription IDs, city override, unlimited changes
- **SavedSearch** — title slug, experience bucket, up to 6 cities (one per user). New signups auto-seeded with all 6 metros.
- **Job** — normalized job data from scraper
- **JobMatch** — links SavedSearch to Job
- **DailyRun** — sync run tracking
- **BaseResume** — user's uploaded resume (one per user). Stores filename, on-disk path, content type, and extracted text.
- **TailoredResume** — per (user, job) tailored PDF. Generated during the daily sync; one PDF per match.

## Open Access (any signed-in user)

`is_superuser_email` returns True for any non-empty email, so every signed-up user gets:

- Both PM + PgM roles matched
- 5+ years experience filter (was 8+ for the original superuser)
- $180K+ salary filter
- Bypasses all billing/city limits

The configured SUPERUSER_EMAIL still exists in catalog.py but no longer governs scope — it's only useful for UI copy or future per-superuser carve-outs.

## Resume + Tailoring

- Users upload a base resume at `/resume` (PDF or DOCX, 5 MB max). Text is extracted via `pypdf` / `python-docx` and stored alongside the file path.
- Daily sync calls `app.sync.generate_tailored_resumes()` after `rebuild_matches()`. For each new (user, job) match where the user has a base resume, it:
  1. Sends base text + job posting to the Anthropic Claude API (model: `ANTHROPIC_MODEL`, default `claude-haiku-4-5-20251001`).
  2. Renders the tailored text to PDF via `reportlab`.
  3. Stores the PDF under `RESUME_TAILORED_DIR/user-<id>/job-<id>.pdf` and records the path in `TailoredResume`.
- Without `ANTHROPIC_API_KEY` set the call falls back to the base text (so the pipeline still produces a downloadable PDF).
- Uploading a new base resume clears all existing TailoredResume rows so they regenerate against the new base.
- Dashboard renders a "Tailored Resume" button on every match card that has a TailoredResume row.
- Required env: `ANTHROPIC_API_KEY=sk-ant-...` in `.env`. Optional: `ANTHROPIC_MODEL`, `RESUME_UPLOAD_DIR`, `RESUME_TAILORED_DIR`, `RESUME_MAX_UPLOAD_BYTES`.

## Dashboard Behavior

- Shows jobs from job_matches table (DB matches), falling back to preview_matches from shared_jobs.json
- **2-day recency filter**: uses posted_at when available, falls back to found_at. Uses calendar-day midnight cutoff (naive datetimes for SQLite compatibility)
- Salary only displayed when a real value exists (no placeholder text)
- Jobs grouped by city

## Billing (Scaffolded)

- $2.99/mo city plan — replaces default 3 cities with custom ones
- $9.99 one-time — unlimited saved search changes (free tier gets 2)
- Stripe integration wired in code, needs real keys in .env

## Key Config

- Default free cities: New York NY, Atlanta GA, Miami FL
- 10 supported cities total (catalog.py)
- 2 title options: Technical Product Manager, Technical Program Manager
- 4 experience buckets: 0-2, 3-6, 7-9, 10+
- VALID_POST_DAYS = 2 in scraper
- MIN_SALARY = 180_000 in scraper

## REQUIRED Workflow for Every Code Change

Every change to this app follows this loop. **Tests gate the push** — a red suite means the change does not get pushed until it is fixed.

1. Edit the code on the server (or scp from local).
2. Restart the service: `systemctl restart jordansjobfinder`
3. Run the curl smoke check (below) — confirms the service comes back up cleanly.
4. **Run the test suite**: `cd /var/www/jordansjobfinder && ./scripts/run_tests.sh`
5. If any test fails → fix the underlying issue and re-run from step 2. Do not push red.
6. Commit + push to `origin master`.

Other rules:

- The scraper takes ~40 min to run — the sync cron must stay well after it.
- After fixing data issues, re-run the sync (see commands below).

## Test Suite

The pytest suite lives in `tests/` and covers route reachability, auth flows,
the dashboard's regression guards (e.g. Settings link must stay gone), matching
logic for superuser + regular users, and saved-search validation.

- Runner: `./scripts/run_tests.sh` (installs pytest into `.venv` if missing)
- Dev deps: `requirements-dev.txt` (`-r requirements.txt` + `pytest`)
- Config: `pytest.ini`
- Fixtures: `tests/conftest.py` — spins up a Flask app with a throwaway SQLite
  DB, disables CSRF + rate limiting, and resets all tables between tests.

Add a test whenever you add a route, change matching behavior, or remove a UI
element you don't want creeping back. The dashboard regression guard
(`tests/test_dashboard.py::test_dashboard_does_not_link_to_settings`) is the
template for "don't let this come back" tests.

## Curl Smoke Check (run after restart, before the test suite)

All should return 200 or 302. Any 500 means the change broke something — fix it before running the suite.

- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/          (expect 200)
- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/dashboard  (expect 302 or 200)
- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/login      (expect 200)
- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/sign-in    (expect 200)
- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/settings   (expect 302 or 200)
- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/billing    (expect 302 or 200)
- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/search     (expect 302 or 200)
- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/matches    (expect 302)
- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/resume     (expect 302)

Any 500 response = broken. Check logs with: journalctl -u jordansjobfinder --no-pager -n 30

## Known Gotchas

- **SQLite stores naive datetimes** — never compare timezone-aware datetimes directly against DB columns. Strip tzinfo or use naive cutoffs.
- **shared_jobs.json dates ARE timezone-aware** (ISO format with +00:00) — strip tzinfo before comparing with naive cutoffs.
- **Workday detail pages contain garbage numbers** — the salary parser caps at $2M and the scraper discards salaries below $180K.
- **The scraper overwrites shared_jobs.json each run** — the sync cron must run AFTER the scraper finishes (currently 1 hour gap).

## Common Commands

- SSH in: ssh root@159.203.110.79
- Restart app: systemctl restart jordansjobfinder
- Check app status: systemctl status jordansjobfinder
- View scraper log: tail -50 /var/www/jordansjobfinder/scraper.log
- View sync log: tail -10 /var/www/jordansjobfinder/app-sync.log
- View error log: journalctl -u jordansjobfinder --no-pager -n 30
- Run manual sync: cd /var/www/jordansjobfinder && set -a && . ./.env && set +a && .venv/bin/python manage.py run-daily-sync
- Init/reset DB: cd /var/www/jordansjobfinder && set -a && . ./.env && set +a && .venv/bin/python manage.py init-db
- Commit and push: cd /var/www/jordansjobfinder && git add <files> && git commit -m "message" && git push origin master
