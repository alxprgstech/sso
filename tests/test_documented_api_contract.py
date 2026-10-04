"""The documented route snapshot must match the actual FastAPI registration."""

import json
from pathlib import Path

from app.main import app


def route_contract():
    # FastAPI defers included routers; OpenAPI contains their effective paths.
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    )


def test_documented_route_snapshot_matches_application():
    source = Path(__file__).resolve().parents[1] / "docs/api-routes.json"
    documented = json.loads(source.read_text(encoding="utf-8"))
    assert [tuple(value) for value in documented["routes"]] == route_contract()
    assert documented["version"] == app.version
    assert {
        ("POST", "/oauth/token"),
        ("GET", "/api/v1/admin/audit"),
        ("POST", "/api/v1/auth/reauthentication"),
        ("POST", "/api/v1/mfa/passkey/register/verify"),
    } <= set(route_contract())
    markdown = source.with_name("api.md").read_text(encoding="utf-8")
    assert all(f"`{path}`" in markdown for _, path in route_contract())
