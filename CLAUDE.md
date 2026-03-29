# Jordan's Job Finder

## What This App Does

A Flask web app + daily scraper that finds technical **Product Manager** and **Program Manager** jobs for Jordan across NYC, Atlanta, and Miami. It scrapes 100+ company career pages daily and surfaces matches based on role, seniority, location, salary, and tech focus.

**Live at:** https://jordansjobfinder.com
**Server:** 167.71.170.219 (DigitalOcean)
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

- **6:00 AM ET** — scraper.py runs (~40 min), scrapes all ATS platforms, writes shared_jobs.json
- **7:00 AM ET** — manage.py run-daily-sync imports shared_jobs.json into DB, rebuilds user matches

## Scraper Pipeline (scraper.py)

Scrapes 5 ATS platforms: Workday (~90 companies), Greenhouse (~30), Lever, Eightfold, custom Playwright (JPMorgan, Goldman, MetLife, Google, Meta, Amazon).

Filter chain for each job:
1. **Role** — title contains "product manager" or "program manager"
2. **Seniority** — NYC requires VP-level; Atlanta/Miami accept VP or Senior
3. **Location** — must be in NYC, Atlanta, or Miami
4. **Recency** — posted within last 2 days
5. **Salary** — $180K+ floor (capped at $2M to filter garbage numbers from page HTML)
6. **Tech focus** — 3+ tech keywords in description (agile, cloud, API, etc.)

Outputs: jobs.html (static public board), jobs_store.json, shared_jobs.json, seen_jobs.json

## Database Models (6 tables)

- **User** — email, password hash
- **MagicLinkToken** — scaffolded, not active
- **Subscription** — Stripe customer/subscription IDs, city override, unlimited changes
- **SavedSearch** — title slug, experience bucket, 3 cities (one per user)
- **Job** — normalized job data from scraper
- **JobMatch** — links SavedSearch to Job
- **DailyRun** — sync run tracking

## Superuser

divinejdavis@gmail.com is the superuser (defined in catalog.py). Gets:
- Both PM and PgM roles matched
- 8+ years experience filter
- $180K+ salary filter
- Bypasses all billing/city limits

## Dashboard Behavior

- Shows jobs from job_matches table (DB matches), falling back to preview_matches from shared_jobs.json
- **2-day recency filter**: uses posted_at when available, falls back to found_at
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

## Important Workflow Rules

- **Always commit + push to GitHub (origin master) after every code change**
- The scraper takes ~40 min to run — the sync cron must be scheduled well after it
- After fixing data issues, re-run the sync (see commands below)
- Restart the app after code changes: systemctl restart jordansjobfinder

## Common Commands

- SSH in: ssh root@167.71.170.219
- Restart app: systemctl restart jordansjobfinder
- Check app status: systemctl status jordansjobfinder
- View scraper log: tail -50 /var/www/jordansjobfinder/scraper.log
- View sync log: tail -10 /var/www/jordansjobfinder/app-sync.log
- Run manual sync: cd /var/www/jordansjobfinder && set -a && . ./.env && set +a && .venv/bin/python manage.py run-daily-sync
- Init/reset DB: cd /var/www/jordansjobfinder && set -a && . ./.env && set +a && .venv/bin/python manage.py init-db
- Commit and push: cd /var/www/jordansjobfinder && git add <files> && git commit -m "message" && git push origin master
