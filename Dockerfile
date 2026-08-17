# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache \
      "Django>=5.2,<6.0" "django-oauth-toolkit>=3.4,<4.0" \
      "djangorestframework>=3.18" "drf-spectacular>=0.30" \
      "psycopg[binary]>=3.2" "gunicorn>=23" "whitenoise>=6.6" \
 && uv pip install --system --no-cache --no-deps -e .

COPY manage.py entrypoint.sh ./
RUN chmod +x entrypoint.sh
EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
