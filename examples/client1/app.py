"""Analytics demo client. Run with one worker; see examples/README.md."""

from examples.demo_app import make_demo_app

app, sso_client, sessions = make_demo_app(
    title="ALXPRGS Analytics (Client 1)",
    heading="Сервис 1: Портал аналитики",
    client_id="client_analytics_app",
    redirect_uri="http://localhost:8001/callback",
    peer_url="http://localhost:8002/login",
    api_path="/api/analytics",
)
