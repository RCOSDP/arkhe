# arkhe のイメージ。**依存は pyproject の [app] だけ**（arkspec と resolution は
# stdlib しか使わないので、本来ここに要るのは HTTP と DB の分だけ）。
#
# **`uv.lock` どおりに入れる。** 上限を書いていないので、`pip install .` では
# 焼き直すたびに中身が変わる——同じ Dockerfile と同じコミットから別のイメージが
# できるのは、追跡できない障害の温床になる。`--frozen` は lock と pyproject が
# ずれていたらそこで落とす（ずれたまま通るほうが困る）。
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# **依存だけを先に入れる。** ソースを変えても、依存が変わっていなければ
# この層は再利用される。
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra app

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
RUN uv sync --frozen --extra app

EXPOSE 8000
# 既定は minter + admin。resolver として動かすなら ARKHE_RESOLVER=1 を渡す。
CMD ["uvicorn", "arkhe.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
