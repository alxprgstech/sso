"""Actual production middleware in a fresh process; no SQL or network mocks."""

import json
import os
import subprocess
import sys

from tests.test_production_keys import production_values  # noqa: F401


def test_cors_production_does_not_trust_local_origins(production_values):  # noqa: F811
    environment = os.environ.copy()
    environment.update(
        {key: str(value) for key, value in production_values.items() if key != "_env_file"}
    )
    environment.update(
        PYTHONPATH="backend",
        FEATURE_TOTP_ENABLED="false",
        FEATURE_PASSKEY_ENABLED="false",
        FEATURE_RECOVERY_CODES_ENABLED="false",
        FEATURE_EMAIL_VERIFICATION_ENABLED="true",
        SENTRY_ENABLED="false",
        SENTRY_FRONTEND_ENABLED="false",
        SENTRY_REPLAY_ENABLED="false",
    )
    code = """import asyncio,json,httpx
from app.main import app
from app.config import get_settings
assert get_settings().ENVIRONMENT == 'production'
async def check():
    results=[]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://auth.example.test') as client:
        for origin in ('https://auth.example.test','http://localhost:3000','http://localhost:5173','http://auth.example.test','https://foreign.example.test'):
            r=await client.options('/api/v1/auth/me',headers={'Origin':origin,'Access-Control-Request-Method':'GET'})
            results.append([r.status_code,r.headers.get('access-control-allow-origin')])
    print(json.dumps(results))
asyncio.run(check())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "Production CORS process failed (details withheld)"
    assert json.loads(result.stdout) == [
        [200, "https://auth.example.test"],
        [400, None],
        [400, None],
        [400, None],
        [400, None],
    ]
