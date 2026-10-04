# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS builder
ARG ALX_BUILD_SHA

WORKDIR /src
COPY requirements-lock.txt /tmp/requirements-lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lock.txt
COPY backend /src/backend
COPY VERSION /src/VERSION
RUN ALX_BUILD_SHA="$ALX_BUILD_SHA" python -c 'import json,os,pathlib,re; v=pathlib.Path("VERSION").read_text().strip(); s=os.environ["ALX_BUILD_SHA"]; assert re.fullmatch("[a-f0-9]{40}",s), "Supply verified ALX_BUILD_SHA"; pathlib.Path("backend/app/_build_info.json").write_text(json.dumps(dict(version=v,commit_sha=s,release=f"alxprgs-sso@{v}+{s}")))' \
    && python -m build --wheel --no-isolation --outdir /wheels backend

FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-runtime-lock.txt /tmp/requirements-runtime-lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements-runtime-lock.txt \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin sso
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-deps /wheels/*.whl && rm -rf /wheels
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/alembic.ini
USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c 'import urllib.request; from urllib.parse import urlsplit; from app.config import get_settings; r=urllib.request.Request("http://127.0.0.1:8000/health/live", headers={"Host":urlsplit(get_settings().BASE_URL).netloc}); urllib.request.urlopen(r,timeout=3).close()' || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
