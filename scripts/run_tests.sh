#!/usr/bin/env bash
# Run the full Jordan's Job Finder test suite.
# Use before every commit + push. A red test blocks the push.
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"

if [[ ! -d "$APP_DIR/.venv" ]]; then
  echo "No .venv found at $APP_DIR/.venv. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
  exit 1
fi

# Install pytest if it's missing.
if ! "$APP_DIR/.venv/bin/python" -c "import pytest" >/dev/null 2>&1; then
  echo "Installing pytest into the project venv..."
  "$APP_DIR/.venv/bin/pip" install -q -r requirements-dev.txt
fi

# Tests provide their own SECRET_KEY / DATABASE_URL — don't leak real env in.
unset SECRET_KEY DATABASE_URL SUPERUSER_EMAIL \
      STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET \
      TURNSTILE_SECRET_KEY TURNSTILE_SITE_KEY || true

exec "$APP_DIR/.venv/bin/python" -m pytest "$@"
