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

- **1:00 AM ET (05:00 UTC)** — single cron chain (moved from 5 AM 2026-07-20 so
  the longer nationwide sweep finishes before morning): scraper.py →
  scraper_finance.py → scraper_sales.py → scraper_it.py → scraper_hr.py →
  scraper_ops.py (combined SCM+project+analyst, ONE sweep of the shared
  employer union via scraper_scm.run_multi) → manage.py run-daily-sync.
  Do NOT re-add the standalone scm/project/analyst entries — that's the
  triple-sweep that blew the chain past 5 hours.

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
`infer_pm_city()` across all supported metros (13 as of 2026-07-19 — the
original 7 plus Chicago, Phoenix, San Antonio, San Diego, Jacksonville, and
Philadelphia, completing top-10-US-city coverage; see PM_METROS ordering
comments for the collision rules: Phoenix before LA for "Glendale, AZ",
San Antonio before Dallas's Texas catch-alls). This avoids re-fetching the
same board once per city. `infer_pm_city` checks metros in a deliberate order —
Dallas LAST — because `DALLAS_LOCS` carries broad Texas catch-alls (", tx",
"texas") and a bare "arlington" that would otherwise swallow Houston / DC. Every
endpoint was auto-discovered + verified HTTP 200 from the droplet IP (Workday
version+site brute-probed; Greenhouse/Lever token). The same verified set is
appended to the finance + sales vertical lists (which already infer city). See
`tests/test_scraper_multi.py` for the inference + list-integrity guards.

### Top-10-city $1B+ wave (2026-07-19)

60 new $1B+ employers added to the multi lists for the top 10 US cities:
57 Workday + Axon/Fanatics (Greenhouse) + Dun & Bradstreet (Lever). Every
endpoint verified HTTP 200 from the droplet IP via the ATS APIs
(Workday CXS jobs POST / Greenhouse boards / Lever postings). Sub-$1B or
revenue-unverifiable candidates (Availity, Newfold) were dropped, as were 7
tenants whose Workday site name couldn't be discovered (Live Nation,
Activision, Petco, Scripps Health, Grubhub, GoDaddy, Radian — 422/401 on all
probed site names; revisit if needed). Revenue strings added to
app/company_revenue.py (gotcha tenants: Cencora=myhrabc, Radian=compass,
Microchip=microchiphr, RYAM=myrayonieram, Citi site name is literally "2").
Follow-up option: append this set to the finance/sales vertical lists — their
city sets are pinned, so it's invisible until those verticals get the new
metros; skipped to keep the 5 AM scrape window safe.

### Charleston SC coverage + NYC $1B floor (2026-07-07)

Charleston SC is selectable (census picker). Five Charleston-area employers
added to `WORKDAY_MULTI` so their Charleston postings surface via the
extra-city inference when a user selects "Charleston, SC": MUSC (musc/1/MUSC —
the anchor, ~21 program-manager roles), Boeing (converted from 3 per-city
entries to one multi — 787 plant), Ingevity (HQ), SouthState Bank, Benefitfocus/
Voya (godirect/voya_jobs, HQ). All verified HTTP 200 from the droplet. Blackbaud
(Charleston-HQ) wanted but its Workday landing 406s (WAF) so its site name is
unverifiable — left out. Note: extra-city matching is city-name+state, so
"Charleston, SC" catches Charleston + North Charleston but not Ladson/Summerville
(those are separately selectable).

NYC list trimmed to **$1B+ revenue only**: removed 22 sub-$1B companies (mostly
private prop-trading shops with <$1B trading revenue + mid-size startups):
Airtable, AQR, Brex, Capstone, Discord, ExodusPoint, Five Rings, Gemini, GitLab,
Jump Trading, Justworks, Lone Pine, Magnetar, Marqeta, Marshall Wace, PDT
Partners, Plaid, Schonfeld, Squarepoint, Tower Research, Waymo, WorldQuant.
Tests: `tests/test_scraper_charleston.py`.

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

## Supply Chain Management Vertical (scraper_scm.py, 2026-07-08)

Sixth vertical (`vertical="scm"`), user-selectable ("Supply Chain Management
(SC · $1B+)"): supply-chain / logistics / procurement / sourcing roles
(analyst through manager, `matching.title_is_scm`) at the $1B+ employer union
(reused from scraper_it) plus verified Charleston employers (Boeing, Ingevity,
SouthState), scoped to **South Carolina's major metros**: charleston-sc
(Lowcountry), columbia-sc (Midlands), greenville-sc (Upstate incl.
Spartanburg), rock-hill-sc (York County) — `SCM_DEFAULT_CITIES`, free plan
caps to the first 3. No salary/experience filter (the $1B+ + SC-location
constraints do the filtering). 7-day board window (results.BOARD_WINDOW_DAYS).
Runs in the 9 AM cron after scraper_hr.py; writes shared_jobs_scm.json. SC
city slugs added to catalog/sync/results/analytics label maps. Tests:
`tests/test_scm_vertical.py`.

### Verified SC $1B+ employer registry (scraper_sc_employers.py, 2026-07-11)

`scraper_sc_employers.py` is the **per-state big-employer registry template**:
`SC_WORKDAY_1B` + `SC_GREENHOUSE_1B` are 15 employers with >$1B revenue and
real SC operations, each careers endpoint **probed HTTP 200 from the droplet**
(Michelin, GE Vernova, Trane, 3M, KION, Sonoco, Prisma Health, Duke Energy,
Unum/Colonial Life, MUSC, Roper St. Francis, LPL, Movement Mortgage, Atrium,
Red Ventures + Boeing). Merged into `SCM_WORKDAY_COMPANIES` /
`SCM_GREENHOUSE_COMPANIES` so their SC jobs surface across the SC tracks.
Excluded: BCBS-SC (`ourhrconnect`/SCBlues) 422s the datacenter IP. Deferred
(unsupported ATS — need scraper_ats_extra support): Nucor, Volvo, Milliken,
Timken, ZF, BMW (Taleo), Bosch/Continental (SmartRecruiters), Fluor
(Eightfold), ScanSource (UKG), Lockheed (BrassRing), Dominion, Honeywell,
Cummins, etc. To roll out another state, clone this file with its verified set.

## Project Management Vertical (scraper_project.py, 2026-07-11)

Seventh vertical (`vertical="project"`), user-selectable ("Project Management
(SC · $1B+)"): project-management roles (coordinator → director, any industry —
`matching.title_is_project`, no IT signal required unlike the IT track). Reuses
the SC $1B+ employer union, SC-metro inference, and 7-day window from the SCM
track via the **parameterized `scraper_scm.run(title_filter, vertical, …)`** —
`scraper_project.py` is a thin wrapper that swaps only the title filter + the
vertical tag (no salary/experience filter). Writes `shared_jobs_project.json`;
runs in the 9 AM cron **after scraper_scm.py**, before the sync. `SCM`'s
`scrape_workday`/`scrape_greenhouse`/`make_job` were parameterized (defaults keep
SCM behavior). Wired through catalog/matching/ingest/results/routes/analytics.
Tests: `tests/test_project_vertical.py`. NOTE: undated Workday postings (empty
`postedOn`, e.g. many MUSC roles) are dropped by the recency filter — a shared
SCM/Project limitation, not yet addressed.

## Board Social Proof — "N others applied" (2026-07-11)

Each dashboard job card shows how many OTHER users applied to that job from the
site (`applications.other_applicant_counts` — distinct `AppliedJob.user_id` by
URL, excluding the viewer). Surfaced as `match["applied_by_others"]` in
`results.load_db_matches`, rendered under the card meta. Tests in
`tests/test_applied.py`.

## Interview Prep — Questions section removed (2026-07-11)

The "Questions to ask" section was removed from interview prep at owner request
(template + prompt + `sanitize_plan` no longer produce it). Company background
and the deterministic Salary expectations block remain. Cached plans keep the
now-unused `questions_to_ask` key in JSON but it never renders.

## HR Coordinator Vertical (scraper_hr.py)

Fifth vertical (`vertical="hr"`), user-selectable: picking "HR Coordinator /
Generalist (5+ yrs)" on `/search` creates the `hr` SavedSearch (pinned to
**York PA, Lancaster PA, Philadelphia PA, Harrisburg PA** —
`HR_DEFAULT_CITIES`; the 3-city picker is PM-only) and its tab appears
immediately (matches rebuilt on the spot). Scope: HR coordinator + the level
above (generalist/specialist; "senior …" variants pass; director/VP/head-of
excluded). **No salary requirement and no experience exclusion** (5+ years
candidates qualify for all coordinator/generalist levels). 7-day windows both
sides, same as IT. Employer set = the IT union + the regional extra-ATS
platforms (the only reach into York/Lancaster). Runs in the 9 AM cron chain
after scraper_it.py; writes `shared_jobs_hr.json`. Selecting any non-PM title
on /search now upserts THAT vertical's search via `VERTICAL_DEFAULT_CITIES`
(previously it corrupted the PM search). Tests: `tests/test_hr_vertical.py`.

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

## Vertical Overhaul (2026-07-19)

- **Project management merged into the PM track**: the picker option is gone;
  a PM saved search matches `vertical in ("pm","it","project")` jobs
  (`_search_matches_job`). One-time `manage.py migrate-project-searches`
  converts/drops legacy project searches. scraper_project.py still runs and
  feeds `vertical="project"` — its jobs now surface on PM boards.
- **Finance**: top-10-city wave appended to FINANCE_WORKDAY_COMPANIES (+54
  boards); new IC keyword group `entry-finance-risk-compliance`
  (risk/compliance/AML-KYC/actuarial/quant/pricing/fund-ops/client-service);
  search terms += actuarial, compliance. Scrape runtime grows accordingly.
- **SCM nationwide**: scraper_scm.py covers the 13 metros + SC four (ordered
  patterns, Dallas catch-alls last), adds the wave employers, and now also
  matches manufacturing-operations ICs (production planner, quality/process/
  manufacturing/industrial engineer, lean/CI, EHS). Defaults lead with
  Chicago/Philadelphia/Houston.
- **HR nationwide**: scraper_hr.py adds the same nationwide metros (PA metros
  stay first in defaults for the original audience) + wave employers.
- **Data/Business Analyst vertical** (`analyst`): new selectable title
  `data-business-analyst`; scraper_analyst.py is a thin wrapper over
  scraper_scm.run() (same employer union/metros, analyst terms + title
  filter). Finance vocabulary excluded from analyst keywords so postings
  don't flip verticals between syncs (DB upsert is by URL). 7-day board
  window. Cron must run scraper_analyst.py before run-daily-sync.

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

## Resume-Derived Experience Matching (2026-07-19)

- `app/experience.py` — `estimate_resume_years()` date-parses employment ranges
  ("Jan 2018 – Present", "03/2019 – 09/2022", "2014–2017") from the resume's
  extracted text, merges overlapping intervals (concurrent roles count once),
  and stores the rounded total on `BaseResume.years_experience` at upload time.
  Deterministic — no AI call. `bucket_for_years()` (moved here from
  interview.py) maps years → the 0-2/3-6/7-9/10+ bands.
- **Resume wins over the manual picker**: sync + preview matching use the
  resume years when present; the saved-search experience picker is only shown
  to (and used for) users with no resume / no parseable dates.
- **Qualification semantics, NOT band overlap** (`candidate_qualifies()` /
  `resume_years` kwarg on `match_job_for_user`): a job matches when its
  required MINIMUM years <= the candidate's years. Band overlap was shipped
  first and blanked senior users' boards — a 10-year candidate vs "8+ years
  required" doesn't overlap the 10+ band. Jobs with unparseable requirements
  stay excluded, as before.
- Uploading a resume recomputes years and immediately calls
  `rebuild_matches_for_user`. Dashboard shows a banner: "based on your resume —
  about X years of experience — these are the jobs for you"; users without a
  resume see an upload prompt instead.
- One-time backfill for pre-existing resumes: `python manage.py backfill-resume-years`
  (also rebuilds all matches). SQLite migration is automatic in `init_db()`.

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

## City Picker + One-Title Rule (2026-07-06)

- **Any US city over 50k population** is selectable for the PM search's three
  cities: `/search` shows state-first cascading pickers (CSS-only-safe:
  `static/js/citypicker.js` is self-hosted; no-JS fallback = optgroup-per-state
  selects). Dataset vendored at `app/static/data/us_cities_50k.json` (Census
  sub-est2023, 801 cities; name cleanups: Boise City→Boise, Urban
  Honolulu→Honolulu, Ventura; VT/WV have no 50k+ place). Loader/validators in
  `app/uscities.py`; canonical label is "City, ST". Each state's list is
  ordered **most-populous first** (POPESTIMATE2023) so the biggest cities top
  the dropdown; the template renders in list order. `citypicker.js`
  **detaches/re-attaches optgroups** on state change (does NOT toggle
  hidden/disabled — Safari still shows disabled/hidden optgroups in the native
  picker, which leaked every state's cities into one dropdown).
- **Matching beyond the metros**: `matching.location_matches_city` (city name
  + state signal in the raw location) is consulted by sync + preview when the
  label isn't a built-in metro. The PM multi-list scrapers keep non-metro
  postings tagged `city="extra"` (salary-optional) when the location matches
  any label on someone's PM search (`load_active_extra_cities()` reads the DB
  at scrape start) — so newly picked cities start filling on the next scrape.
- **One job title per account — EVERYONE, admin included** (exemption removed
  same day at owner request: "only show one job selection at a time"): signup
  seeds ONLY the PM track; choosing any title on /search REPLACES the other
  tracks (`_enforce_single_title`). All existing users incl. divinejdavis were
  trimmed to one track on 2026-07-06. Dashboard tab row = one tab + a
  "Switch to HR Coordinator+" pill + an "Edit search" pill. The /search title
  dropdown offers `SELECTABLE_TITLES` — similar titles combined, ONE option
  per track (PM, Finance, Sales, IT, HR); legacy sub-track slugs stay valid.
- Tests: `tests/test_city_picker.py`.

## AI Interview Prep — Pro only (restructured 2026-07-10)

A **Pro ($19.99)**-gated feature: on any match card an "Interview Prep" button
links to `/interview/<job_id>`. For Pro users it generates (once, then cached
in the `interview_plans` table) a prep package via Anthropic
(`app/interview.py::generate_interview_plan` → `sanitize_plan`) with three
sections:

1. **Company background** — factual overview + facts to know walking in (the
   prompt forbids inventing facts about unrecognized companies).
2. **Questions to ask** — questions the CANDIDATE asks the interviewer, grouped
   (role / team / company).
3. **Salary expectations** — deterministic (`build_salary_expectation`), NOT
   model numbers when data exists. Preference: (a) **market** — percentile band
   over real scraped salaries in the job's city+vertical, positioned by the
   candidate's years of experience (model infers years from the resume →
   `bucket_for_years` → analytics.EXPERIENCE_BANDS; fallback = saved-search
   bucket); (b) **posting** — the job's own salary range; (c) **model** — the
   LLM estimate. Market basis needs ≥3 sane points.

Plans stored in the pre-2026-07-10 shape (14-day schedule) are detected by the
missing `company_background` key, render the generate CTA again, and are
replaced in place on the next POST. Non-Pro users see an upgrade CTA (button
shown to everyone as an upsell; the POST + gate live in
`routes.interview_plan`, gate = `routes.is_pro` → city_limit>=10 or admin).
Prompt caps job desc to 8K / resume to 12K and treats the scraped posting as
untrusted data. Tests: `tests/test_interview.py`.

## Plans, Resume Quota, Search Lock, Profile (2026-07-08)

Repriced + restructured tiers (LIVE Stripe):
- **Free**: 3 cities, 10 AI-resume creations LIFETIME.
- **Plus $4.99/mo** (checkout `city-5`, was $9.99): 5 cities + 25 resumes/month.
- **Pro $19.99/mo** (`city-10`): 10 cities + unlimited resumes.
Quota table in payments.RESUME_QUOTA keyed by city_limit; consume_resume_credit
spends one on each NEW on-demand tailoring (re-downloads free). Monthly reset
via resume_period_start for paid; free never resets. **Nightly bulk
tailored-resume pre-gen is DISABLED** (it handed free users unlimited resumes) —
all tailoring is on-demand + quota-gated.

**City cap bug fix**: non-PM tracks (finance/sales/IT/HR) seeded FIXED city
sets (finance=11) ignoring the plan limit, so a free user picking Corporate
Finance saw 11 cities. Now every track caps to city_limit_for(user); existing
over-limit searches trimmed in prod; admin + Frank comped to city_limit=10.

**30-day search lock**: saving freezes the whole search (title+experience+
cities) for 30 days (subscriptions.search_locked_until); the /search form
disables + rejects while locked; upgrading a tier clears the lock. Owner never
locked.

**Profile hub** (`/profile`, profile.html): plan + resume credits, Edit search,
resume upload (moved from /resume, which now redirects here), and **Manage
subscription** → Stripe billing portal (create_billing_portal_session; portal
config bpc_… created). Nav "Resume" replaced by "Profile"; dashboard "Edit
search" pill removed. Tests: tests/test_plans.py.

## Billing — City Tiers (LIVE Stripe, 2026-07-06)

- **3 cities free / 5 for $9.99/mo / 10 for $19.99/mo** — checkout kinds
  `city-5` / `city-10` (payments.CITY_TIERS), live Stripe keys + price IDs in
  .env (STRIPE_CITY5_PRICE_ID / STRIPE_CITY10_PRICE_ID; products created via
  API). `subscriptions.city_limit` column drives the /search slot count and
  validation ceiling (3..limit; owner account always 10). Webhook endpoint
  consolidated to ONE at /stripe/webhook (3 stale duplicates deleted; fresh
  whsec in .env). Upgrades cancel the previous Stripe sub in
  `_fulfill_city_tier` (no double-billing); cancel/`customer.subscription.
  deleted` resets to 3 and trims the search to its first 3 cities. Signup now
  seeds the free 3-city set (NYC/ATL/MIA) instead of 7 metros; existing
  non-admin PM searches were trimmed 2026-07-06. NOTE: `is_superuser_email`
  is open to everyone, so billing gates use `is_admin_email` — the old
  superuser gate silently blocked ALL checkouts. Legacy $2.99 city-plan and
  $9.99 unlock code paths remain but are no longer offered in the UI.
  Tests: tests/test_city_tiers.py.

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

## Shared Scraper Helpers (2026-07-21)

Two root-level modules every scraper imports. Both exist because the same bug
class kept reappearing in six duplicated copies of the same logic.

- **metro_decoys.py** — place names that merely *contain* a metro's token but
  belong to another market. Every city matcher here is a substring test, so
  NYC's bare `"manhattan"` matched "Manhattan Beach, CA" (Skechers' HQ) and
  "Brooklyn Park, MN" (Target, Medtronic). `strip_decoys(loc, code)` blanks a
  metro's decoys before that metro's patterns run, so LA still matches
  "manhattan beach" normally. **Fix collisions by adding a decoy, not by
  reordering the metro list** — ordering only works when the true metro is
  checked first, which can't hold for every metro at once.
- **greenhouse_urls.py** — `greenhouse_job_url(job, token)` replaces raw
  `absolute_url`. Boards that redirect to a company careers site return
  `<site>/jobs/search?gh_jid=<id>`, which deep-links only while that site
  publishes the req; otherwise "View Role" opens the whole job index. Probes
  once with HEAD and falls back to Greenhouse's hosted application page. It is
  deliberately reluctant — a 4xx keeps the company URL, because these sites
  WAF-block the droplet while serving browsers fine (same trap as the probe
  recipe above).

`scripts/backfill_metro_and_urls.py` repairs postings already on the board for
both bugs. **It fixes the shared_jobs*.json feeds first** — see the gotcha
below.

## Known Gotchas

- **SQLite stores naive datetimes** — never compare timezone-aware datetimes directly against DB columns. Strip tzinfo or use naive cutoffs.
- **shared_jobs.json dates ARE timezone-aware** (ISO format with +00:00) — strip tzinfo before comparing with naive cutoffs.
- **Workday detail pages contain garbage numbers** — the salary parser caps at $2M and the scraper discards salaries below $180K.
- **The scraper overwrites shared_jobs.json each run** — the sync cron must run AFTER the scraper finishes (currently 1 hour gap).
- **The shared_jobs*.json feeds outrank the DB** — `run-daily-sync` re-upserts
  every posting from those files, so a hand-edit to a `jobs` row is silently
  reverted on the next sync. Any data repair must fix the feed too (or delete
  the row outright). Rewriting a posting's URL also strands its old row, since
  the upsert keys on URL — delete the old one or the board shows it twice.
- **Test stubs must cover every feed loader** — `normalized_shared_jobs()` calls
  one `load_*_jobs()` per vertical. An unstubbed one reads the real JSON off
  disk; that's how the ingest blocklist test quietly read production data for
  two days. `tests/test_ingest.py` has a guard that fails when a new loader is
  added without a stub.

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
