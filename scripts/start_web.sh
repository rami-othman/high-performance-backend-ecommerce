#!/bin/sh
set -e

WEB_CONCURRENCY="${WEB_CONCURRENCY:-8}"
GUNICORN_THREADS="${GUNICORN_THREADS:-2}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"

echo "Starting Django with Gunicorn gthread workers"
echo "WEB_CONCURRENCY=${WEB_CONCURRENCY}"
echo "GUNICORN_THREADS=${GUNICORN_THREADS}"
echo "GUNICORN_TIMEOUT=${GUNICORN_TIMEOUT}"

python manage.py migrate

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --worker-class gthread \
  --workers "${WEB_CONCURRENCY}" \
  --threads "${GUNICORN_THREADS}" \
  --timeout "${GUNICORN_TIMEOUT}"
