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
- Requests
- Beautiful Soup
- Playwright
- JSON file storage
- Cron for scheduled runs
- Static HTML generation
- Linux server hosting

## How It Works

The scraper checks a curated set of company career systems, including APIs and browser-rendered job pages. Matching jobs are stored, deduplicated, and written into a static HTML page that is served on the live website.

## Repo Purpose

This repository contains the scraper logic, the generated job page, and the data files that support the live site.
