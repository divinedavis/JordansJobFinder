# Jordan's Job Finder

Live site: https://jordansjobfinder.com

Jordan's Job Finder is a personal job-search website that automatically scans selected company career pages and publishes matching roles to a public webpage.

The site is built for viewing, not for user accounts or app downloads. Visitors do not install anything. They simply open the website and see the latest jobs that match the configured filters.

## What It Does

- Searches targeted company career pages instead of broad job boards
- Filters for product manager and program manager roles
- Applies seniority rules by city
- Filters for technical roles
- Checks compensation when salary data is available
- Keeps the results focused on recent postings
- Publishes the matches to a simple website for quick review

## Current Search Focus

- New York City: VP-level technical PM / PgM roles
- Atlanta: VP or Senior technical PM / PgM roles
- Miami: VP or Senior technical PM / PgM roles

## How Users Experience It

Users do not sign up, install software, or run the scraper locally.

They visit the live site:

https://jordansjobfinder.com

The website displays the latest matching jobs found by the scheduled scraper run.

## Tech Stack

- Python
- Flask
- SQLAlchemy
- Requests
- Beautiful Soup
- Playwright
- JSON file storage
- SQLite for local app development
- Cron for scheduled runs
- Static HTML generation
- Linux server hosting

## How It Works

The scraper checks a curated set of company career systems, including APIs and browser-rendered job pages. Matching jobs are stored, deduplicated, and written into a static HTML page that is served on the live website.

## Repo Purpose

This repository contains the scraper logic, the generated job page, and the data files that support the live site.

## Private App Foundation

The repo now also includes the foundation for the next version of the product:

- passwordless email sign-in
- one saved search per user
- private dashboard pages
- saved-search rules for free and paid city plans
- database models for users, searches, jobs, and matches
- shared-job sync commands that prepare the app for daily per-user matching

## Local Development

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Initialize the local database:

```bash
.venv/bin/python manage.py init-db
```

Run the local app:

```bash
.venv/bin/python manage.py runserver --host 127.0.0.1 --port 5000
```

Run smoke tests:

```bash
.venv/bin/python -m unittest tests/test_app.py
```

Optional app sync commands:

```bash
.venv/bin/flask --app manage.py sync-shared-jobs
.venv/bin/flask --app manage.py rebuild-matches
.venv/bin/flask --app manage.py run-daily-sync
```

## Deployment Scaffolding

The repo now includes:

- [wsgi.py](/Users/divinedavis/job-scraper/wsgi.py) for Gunicorn entry
- [deploy/gunicorn.conf.py](/Users/divinedavis/job-scraper/deploy/gunicorn.conf.py)
- [deploy/jordansjobfinder.service.example](/Users/divinedavis/job-scraper/deploy/jordansjobfinder.service.example)
- [deploy/production.env.example](/Users/divinedavis/job-scraper/deploy/production.env.example)
- [deploy/DEPLOYMENT.md](/Users/divinedavis/job-scraper/deploy/DEPLOYMENT.md)

These are examples only. Final production deployment still needs the real `.env`, SMTP, and Stripe values.

These private-app features still need production secrets and wiring before deployment:

- SMTP credentials for real magic-link email delivery
- Stripe keys, products, and webhooks
- future Google and LinkedIn auth setup
