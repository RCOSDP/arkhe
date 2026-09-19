#!/usr/bin/env bash
# The minter and the resolver share an image. RESOLVER=1 makes it a resolver.
set -euo pipefail

PORT="${JC2ARK_PORT:-8080}"
WORKERS="${JC2ARK_WORKERS:-3}"
# M7: --timeout is set explicitly rather than left at the default of 30 seconds.
# arklet left it unset, and workers were killed when its linear authorisation scan took
# longer than that.
TIMEOUT="${JC2ARK_TIMEOUT:-60}"
GRACEFUL="${JC2ARK_GRACEFUL_TIMEOUT:-30}"

ROLE="${JC2ARK_ROLE:-$([ "${RESOLVER:-0}" = "1" ] && echo resolver || echo minter)}"
export JC2ARK_ROLE="$ROLE"

case "$ROLE" in
  resolver)
    # M8: a resolver runs as a read-only role, so it does not migrate.
    python manage.py collectstatic --noinput >/dev/null 2>&1 || true
    ;;
  admin)
    # The operator screens, which are never exposed publicly. The minter creates the
    # schema.
    python manage.py collectstatic --noinput >/dev/null 2>&1 || true
    ;;
  minter)
    # The schema and the first administrator are created by the minter, which is the
    # writer. Doing it here would mean no migration runs while the admin interface is
    # stopped.
    echo "running migrations"
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput >/dev/null 2>&1 || true
    if [ -n "${JC2ARK_ADMIN_USER:-}" ]; then
      DJANGO_SUPERUSER_PASSWORD="${JC2ARK_ADMIN_PASSWORD:-}" \
        python manage.py createsuperuser --noinput \
        --username "$JC2ARK_ADMIN_USER" --email "admin@example.invalid" 2>/dev/null || true
    fi
    ;;
esac
echo "starting ${ROLE} on :${PORT} (timeout=${TIMEOUT}s)"

exec gunicorn jc2ark.entrypoints.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WORKERS}" \
  --timeout "${TIMEOUT}" \
  --graceful-timeout "${GRACEFUL}" \
  --access-logfile - --error-logfile -
