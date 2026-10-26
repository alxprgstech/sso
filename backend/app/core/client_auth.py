"""RFC 6749 client authentication parsing shared by OIDC and step-up endpoints."""

from __future__ import annotations

from authlib.oauth2.rfc6749.util import extract_basic_authorization
from fastapi import Request

from app.core.exceptions import OAuthErrorException


def extract_client_credentials(
    request: Request,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> tuple[str, str | None]:
    """Read exactly one client authentication method from Basic or form fields.

    Mixing Basic and body credentials is rejected.  The returned secret is never
    written to diagnostics or audit details by this module.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and (len(auth_header) > 4096 or not auth_header.lower().startswith("basic ")):
        raise OAuthErrorException("invalid_client", "Неверный метод аутентификации клиента", 401)
    if auth_header and auth_header.lower().startswith("basic "):
        if client_id is not None or client_secret is not None:
            raise OAuthErrorException(
                "invalid_request",
                "Использование более одного метода аутентификации клиента запрещено (RFC 6749 Section 2.3)",
                400,
            )
        try:
            creds = extract_basic_authorization(
                {"Authorization": "Basic " + auth_header.split(" ", 1)[1]}
            )
            if not creds:
                raise ValueError("Empty credentials")
            cid, csec = creds
            if not 1 <= len(cid) <= 64 or (csec is not None and len(csec) > 128):
                raise ValueError("Invalid client credentials length")
            return cid, csec
        except Exception:
            raise OAuthErrorException(
                "invalid_client", "Некорректный заголовок Basic авторизации", 401
            )
    if not client_id:
        raise OAuthErrorException("invalid_client", "Отсутствует client_id", 401)
    return client_id, client_secret
