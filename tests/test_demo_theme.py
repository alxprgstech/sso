"""Demo rendering/assets unit tests; these do not verify an OIDC login."""

from pathlib import Path

import pytest
from alxprgs_sso.models import UserClaims, WebSessionInfo
from fastapi.testclient import TestClient

from examples.demo_app import make_demo_app


@pytest.mark.parametrize("client_id", ["client_analytics_app", "client_docs_app"])
def test_demo_theme_assets_and_authenticated_markup(client_id: str) -> None:
    app, _, sessions = make_demo_app(
        title="Synthetic UI demo",
        heading="Тестовый портал",
        client_id=client_id,
        redirect_uri="http://localhost/callback",
        peer_url="http://localhost/peer",
        api_path="/api/protected",
    )
    client = TestClient(app, base_url="http://localhost")
    public = client.get("/")
    assert public.status_code == 200
    assert 'data-theme-control aria-label="Тема оформления"' in public.text
    assert '<script src="/theme/theme.js"></script>' in public.text
    assert 'id="btn-login"' in public.text
    for asset in ["theme.js", "palette.css", "demo.css"]:
        response = client.get(f"/theme/{asset}")
        assert response.status_code == 200
        source = Path("frontend/public/theme") / asset
        assert response.content == source.read_bytes()
        assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/theme/other.js").status_code == 404
    assert client.get("/theme/.env").status_code == 404

    identifier, session = sessions.create_session(
        WebSessionInfo(
            user=UserClaims(sub="synthetic-ui", preferred_username="<unsafe>", roles=["user"]),
            access_token="synthetic-ui-access",
            id_token="synthetic-ui-id",
            expires_in=300,
            id_token_claims={"sub": "synthetic-ui"},
        )
    )
    client.cookies.set(f"demo_{client_id}_session", identifier)
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "<unsafe>" not in dashboard.text and "&lt;unsafe&gt;" in dashboard.text
    assert 'aria-label="Тема оформления"' in dashboard.text
    assert 'id="btn-sso-logout"' in dashboard.text
    assert f'name="csrf" value="{session.csrf}"' in dashboard.text
    assert client.post("/logout", data={"csrf": "wrong"}).status_code == 403
    assert (
        client.post("/logout", data={"csrf": session.csrf}, follow_redirects=False).status_code
        == 303
    )
    assert client.get("/api/me").status_code == 401
