# The arkhe image. It installs only the app extra from pyproject: arkspec and
# resolution use nothing but the standard library, so what is needed here is HTTP and a
# database driver.
#
# Installed exactly as uv.lock says. There are no upper bounds, so pip install . would
# put something different in every rebuild, and two images built from the same Dockerfile
# and the same commit differing is where untraceable failures come from. --frozen stops
# if the lock and pyproject disagree, which is better than passing while they do.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# Dependencies are installed first, so that changing the source reuses this layer
# whenever the dependencies have not changed.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra app

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
RUN uv sync --frozen --extra app

EXPOSE 8000
# The default is the minter with the admin interface. Pass ARKHE_RESOLVER=1 for a
# resolver.
CMD ["uvicorn", "arkhe.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
