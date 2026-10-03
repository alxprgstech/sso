"""Explicit new consent step for existing synthetic-user regression scenarios."""

from app.legal import REQUIRED_DOCUMENTS
from app.services.privacy_service import database_now, record_acceptance


async def accept_current_documents(client, login):
    if login.status_code != 200 or login.json().get("mfa_required"):
        return
    documents = await client.get("/api/v1/legal/documents")
    assert documents.status_code == 200
    response = await client.post(
        "/api/v1/auth/legal-acceptance",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
        json={
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": documents.json()["required_versions"],
        },
    )
    assert response.status_code == 200


async def record_test_consent(db, user):
    # Direct service tests explicitly seed a receipt; API tests use the endpoint.
    await db.flush()
    await record_acceptance(db, user.id, REQUIRED_DOCUMENTS, await database_now(db))
    await db.commit()
