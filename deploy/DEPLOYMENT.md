# Jordan's Job Finder App Deployment

This file covers the non-secret production setup for the private app foundation.

## 1. Create the virtual environment on the server

```bash
cd /var/www/jordansjobfinder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 2. Create the environment file

Copy:

```bash
cp deploy/production.env.example .env
```

Then fill in:

- `SECRET_KEY`
- SMTP settings
- Stripe keys and price IDs

## 3. Initialize the database

```bash
.venv/bin/python manage.py init-db
```

## 4. Seed or test local data if needed

```bash
.venv/bin/python manage.py seed-demo
.venv/bin/python manage.py run-daily-sync
```

## 5. Start the app with Gunicorn

```bash
.venv/bin/gunicorn -c deploy/gunicorn.conf.py wsgi:app
```

## 6. Systemd service

Use:

- `deploy/jordansjobfinder.service.example`

Copy it into `/etc/systemd/system/`, adjust the user/group if needed, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable jordansjobfinder
sudo systemctl start jordansjobfinder
sudo systemctl status jordansjobfinder
```

## 7. Nginx reverse proxy

Point your Nginx site config to:

- `127.0.0.1:8000`

The exact Nginx config is still environment-specific and should be added once we know whether the private app will live on the main domain or a subpath/subdomain.

## 8. Daily jobs

For the private app foundation, the daily job should run:

```bash
.venv/bin/python manage.py run-daily-sync
```

That imports the current shared crawl into the app database and rebuilds user matches.

## 9. Remaining secret-dependent work

Production is not complete until these are configured:

- SMTP for real magic links
- Stripe checkout and webhook handling
- final Nginx routing
