"""Documentation demo client. Run with one worker; see examples/README.md."""

from examples.demo_app import make_demo_app

app, sso_client, sessions = make_demo_app(
    title="ALXPRGS Documentation (Client 2)",
    heading="Сервис 2: Портал документации",
    client_id="client_docs_app",
    redirect_uri="http://localhost:8002/callback",
    peer_url="http://localhost:8001/login",
    api_path="/api/docs",
)
