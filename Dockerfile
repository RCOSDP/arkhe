# arkhe のイメージ。**依存は pyproject の [app] だけ**（arkspec と resolution は
# stdlib しか使わないので、本来ここに要るのは HTTP と DB の分だけ）。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
RUN pip install --no-cache-dir '.[app]'

EXPOSE 8000
# 既定は minter + admin。resolver として動かすなら ARKHE_RESOLVER=1 を渡す。
CMD ["uvicorn", "arkhe.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
