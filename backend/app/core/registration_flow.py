"""A mailbox proof cannot substitute for possession of the initiating browser."""

from fastapi import Request, Response

from app.config import Settings


def cookie_name(request: Request, settings: Settings) -> str:
    return (
        "__Host-alx_registration"
        if (request.url.scheme == "https" or settings.ENVIRONMENT == "production")
        else "alx_registration"
    )


def browser_secret(request: Request, settings: Settings) -> str | None:
    value = request.cookies.get(cookie_name(request, settings))
    return value if value and len(value) == 43 else None


def set_browser_secret(
    response: Response, request: Request, settings: Settings, secret: str
) -> None:
    response.set_cookie(
        cookie_name(request, settings),
        secret,
        max_age=3600,
        httponly=True,
        secure=request.url.scheme == "https" or settings.ENVIRONMENT == "production",
        samesite="lax",
        path="/",
    )
