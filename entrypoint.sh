#!/bin/sh
# Exit immediately on any failure, so a broken migration doesn't silently fall
# through to serving traffic against a half-migrated schema.
set -e

# Apply any pending migrations before serving traffic. Safe to run on every
# container start/restart — Django migrations are idempotent (no-op if already applied).
python manage.py migrate --noinput

# Rebuild STATIC_ROOT so nginx (which serves static files directly in prod) has the
# current CSS/JS/admin assets; --noinput avoids an interactive overwrite prompt.
python manage.py collectstatic --noinput

# Hand off to whatever CMD was passed — gunicorn by default (Dockerfile), or the
# `runserver` override in docker-compose.yml for local dev — without duplicating
# the migrate/collectstatic steps in both places.
exec "$@"
