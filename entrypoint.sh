#!/usr/bin/env bash
# minter と resolver は同じイメージ。RESOLVER=1 で resolver になる。
set -euo pipefail

PORT="${JC2ARK_PORT:-8080}"
WORKERS="${JC2ARK_WORKERS:-3}"
# M7: **--timeout を明示する。** 既定の 30 秒に依存しない。arklet はここが未指定で、
# 認可の線形走査が 30 秒を超えたときワーカーが殺されていた。
TIMEOUT="${JC2ARK_TIMEOUT:-60}"
GRACEFUL="${JC2ARK_GRACEFUL_TIMEOUT:-30}"

ROLE="${JC2ARK_ROLE:-$([ "${RESOLVER:-0}" = "1" ] && echo resolver || echo minter)}"
export JC2ARK_ROLE="$ROLE"

case "$ROLE" in
  resolver)
    # M8: resolver は**読み取り専用ロール**で動くのでマイグレーションしない。
    python manage.py collectstatic --noinput >/dev/null 2>&1 || true
    ;;
  admin)
    # **決して外部公開しない**運用者向けの画面。スキーマは minter が作る。
    python manage.py collectstatic --noinput >/dev/null 2>&1 || true
    ;;
  minter)
    # スキーマと superuser は**書き手である minter が用意する**。
    # admin 側に置くと、admin を止めている間にマイグレーションが走らない。
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
