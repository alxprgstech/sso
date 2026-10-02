# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm
ARG ALX_BUILD_SHA

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-lock.txt /tmp/requirements-lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lock.txt
COPY backend /app
COPY VERSION /tmp/product/VERSION
# SHA is a verified build input, never a runtime release override.
RUN ALX_BUILD_SHA="$ALX_BUILD_SHA" python -c 'import json,os,pathlib,re; v=pathlib.Path("/tmp/product/VERSION").read_text().strip(); s=os.environ["ALX_BUILD_SHA"]; assert re.fullmatch("[a-f0-9]{40}",s), "Supply verified ALX_BUILD_SHA"; pathlib.Path("app/_build_info.json").write_text(json.dumps(dict(version=v,commit_sha=s,release=f"alxprgs-sso@{v}+{s}")))' \
    && pip install --no-cache-dir --no-deps --no-build-isolation .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
