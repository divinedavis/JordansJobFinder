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

### Multi-metro $1B+ employer lists (GREENHOUSE_MULTI / LEVER_MULTI / WORKDAY_MULTI)

A second wave of large-cap ($1B+ revenue / unicorn-scale) employers lives in
these three lists. Unlike the per-city lists (one row per company×city), each
multi entry is **fetched once** and the metro is inferred per posting via
`infer_pm_city()` across all 7 supported cities. This avoids re-fetching the
same board once per city. `infer_pm_city` checks metros in a deliberate order —
Dallas LAST — because `DALLAS_LOCS` carries broad Texas catch-alls (", tx",
"texas") and a bare "arlington" that would otherwise swallow Houston / DC. Every
endpoint was auto-discovered + verified HTTP 200 from the droplet IP (Workday
version+site brute-probed; Greenhouse/Lever token). The same verified set is
appended to the finance + sales vertical lists (which already infer city). See
`tests/test_scraper_multi.py` for the inference + list-integrity guards.

### Fortune 1000 Houston coverage (2026-07-04)

All reachable Fortune 1000 Houston-HQ employers are in the PM scraper: 10 new
per-city Workday entries (Plains, Corebridge, Westlake, KBR, Chord, SCI,
Stewart, Occidental, Comfort Systems, DNOW) plus a `collect_houston_extra()`
pass driving scraper_ats_extra's Oracle (Cheniere, NOV, Patterson-UTI,
Oceaneering) and iCIMS (Quanta, Group 1, Kinder Morgan, Kirby) functions with
PM-scope filters; those candidates flow through the normal detail-page
enrichment. Unreachable (no supported ATS): Enterprise Products (legacy
Taleo), CenterPoint + Murphy Oil (hosted SuccessFactors variant), Crown Castle
(UKG), APA, Crescent Energy. Tests: `tests/test_scraper_houston.py`.

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

## IT Project/Program Manager Vertical (scraper_it.py)

Third sibling vertical (`vertical="it"`), built for a specific user (Frank,
fbnorris0502@gmail.com): **mid-to-senior IT project/program manager** roles at
$1B+ employers in **Lancaster PA, Philadelphia PA, Harrisburg PA, and every
Florida metro** (miami, tampa-fl, orlando-fl, jacksonville-fl, plus a
`florida-other` catch-all checked LAST so no FL posting is dropped). The job
only needs to SIT in one of these locations — HQ doesn't matter. **No salary
floor and no experience exclusion** (serves a 10+ years candidate who
qualifies for every level). Title heuristic (`matching.title_is_it_pm`,
duplicated in the scraper per the vertical pattern): project/program-manager
keyword AND an IT signal (word-boundary "IT", software, cloud, ERP, cyber, …),
with construction/facilities/clinical negatives. Writes `shared_jobs_it.json`;
runs in the 9 AM cron chain after scraper_sales.py. Employer set = the UNION
of the verified sales + finance Workday/Greenhouse lists (deduped; the finance
list contributes Vanguard/Malvern, Fidelity/Jacksonville, Raymond James/Tampa)
+ regional extra-ATS platforms. **7-day windows** on both sides (scraper
`RECENCY_DAYS` and `results.BOARD_WINDOW_DAYS["it"]`) because IT-PM roles in
these metros post rarely — the national tracks stay at 2 days. Workday
postings listed as "N Locations" get a detail-page fetch (title+recency
survivors only) to recover the real cities — without it, most big-bank
postings are invisible to the location filter.

**Dashboard/Research tabs are per-user**: `routes.user_verticals()` shows only
the verticals a user has a SavedSearch for. Frank has ONLY the `it` search
(his pm/finance/sales defaults were removed 2026-07-03), so he sees just the
IT tab; everyone else keeps pm/finance/sales and never sees the IT tab.
Tests: `tests/test_it_vertical.py`.

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

## Analytics + Research Tabs

Two nav tabs built on existing data (no schema changes), logic in `app/analytics.py`:

- **Analytics** (`/analytics`, `analytics.html`) — year-in-review of the user's
  applications. Reads the durable `AppliedJob` history (survives the nightly
  rebuild + 2-day board window), groups into a contiguous, zero-filled 12-month
  and 12-week series rendered as pure-CSS bars, plus summary stats (total, this
  week/month/year, busiest month, avg/active week) and by-track / by-market
  breakdowns. `build_application_analytics(applications, now=...)` is pure and
  `now`-injectable for tests. Also renders an **application leaderboard** of
  every user's week/month/year/total counts (`build_application_leaderboard`,
  fed by a User⟕AppliedJob outer join so zero-application users still appear;
  display names are the email local part — full addresses never render). The
  old **Applied** tab is retired: `/applied` 302s to `/analytics` and a nav
  regression guard keeps the tab from creeping back.
- **Research** (`/research?tab=pm|finance|sales`, `research.html`) — market
  value per city on the user's saved search. `build_market_research()`
  aggregates real `Job.salary_min/max` midpoints per market (filtered to a sane
  $40K–$1M band to drop scraper garbage), shows the min/p25/median/p75/max
  distribution, and a **suggested ask** band scaled to the saved
  `experience_bucket` via `EXPERIENCE_BANDS` (more experience → higher
  percentiles). Markets with no salary data are still listed but flagged thin.
  When `user_id` is passed, each market also carries an `applied` block — the
  salary range / median / 'potential' (75th pct) of the jobs the user actually
  applied to in that market (numeric salary resolved from the linked `Job`, or
  parsed from the `AppliedJob.salary_label` snapshot) — plus an
  `applied_overall` summary panel ("Your potential salary").

Tests: `tests/test_analytics.py` (aggregation math, applied-salary per market,
route auth, nav links).

## Security Hardening (2026-07-03 audit)

- **Rate limits** (flask-limiter, Redis-backed via `RATELIMIT_STORAGE_URI` in .env —
  shared across gunicorn workers): login/sign-in 8/min, tailored-resume download
  30/hour, resume upload 10/hour, feedback POST 10/hour. nginx adds a per-IP
  `limit_req` backstop on /login + /sign-in (zone in /etc/nginx/conf.d/security.conf).
- **Account lockout**: 10 consecutive failed logins → 15-min lockout
  (users.failed_login_count / locked_until, helpers in app/security.py).
- **Uploads**: magic-byte sniffing (%PDF- / PK zip) + DOCX decompression-bomb cap
  (50 MB inflated) in app/resumes.py; nginx client_max_body_size 6m.
- **LLM guardrails** (resume tailoring): job description capped at 8K chars, base
  resume 20K (token-cost bomb), prompt instructs the model to treat the scraped
  posting as untrusted data (prompt-injection guard), max_tokens=4000.
- **Config**: production refuses to boot with a placeholder/short SECRET_KEY;
  sessions 14 days; failed-login logs hash the email (no PII).
- **Server**: systemd sandbox on the service (ProtectSystem=strict etc. in
  jordansjobfinder.service.d/hardening.conf), server_tokens off, nightly DB backup
  cron (/usr/local/bin/jjf-backup.sh, 14-day rotation in backups/).
- **GitHub**: secret scanning + push protection + Dependabot security updates +
  private vulnerability reporting enabled; weekly pip bumps via .github/dependabot.yml.
- Tests guarding all of this: `tests/test_security.py`.

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
