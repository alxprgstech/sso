from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


class FeatureDisabledException(HTTPException):
    def __init__(
        self,
        message: str = "Requested feature is disabled by server configuration",
        feature: str | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "feature_disabled",
                "detail": message,
                **({"feature": feature} if feature else {}),
            },
        )


class AuthenticationException(HTTPException):
    def __init__(
        self,
        detail: str = "Неверный логин или пароль",
        error: str = "invalid_credentials",
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": error, "detail": detail, **(extra or {})},
            headers=headers,
        )


class TOTPReplayException(AuthenticationException):
    """A structurally valid TOTP code whose time step is already spent.

    Distinct from a wrong code: the authenticator produced a real code, but it
    was already redeemed (login, elevation or reauthentication). The client
    receives a stable machine code and a bounded wait hint so it can ask for the
    next code instead of retrying the burned one. Security semantics are
    unchanged: a code is never accepted twice.
    """

    def __init__(self, retry_after_seconds: int) -> None:
        retry_after = max(1, int(retry_after_seconds))
        super().__init__(
            "Этот код уже был использован. Введите следующий код из приложения-аутентификатора.",
            error="totp_code_reused",
            headers={"Retry-After": str(retry_after)},
            extra={"retry_after": retry_after},
        )


class AuthorizationException(HTTPException):
    def __init__(
        self,
        detail: str = "Недостаточно прав для выполнения действия",
        error: str = "forbidden",
    ) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": error, "detail": detail},
        )


class OAuthErrorException(HTTPException):
    """Стандартные ошибки протокола OAuth 2.0 / OIDC (RFC 6749 раздел 5.2)."""

    def __init__(
        self,
        error: str,
        error_description: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ) -> None:
        self.error = error
        self.error_description = error_description
        super().__init__(
            status_code=status_code,
            detail={"error": error, "error_description": error_description},
        )


class StepUpError(HTTPException):
    """Stable, non-reflective errors for the transaction step-up protocol."""

    def __init__(
        self,
        error: str,
        detail: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ) -> None:
        self.error = error
        super().__init__(
            status_code=status_code,
            detail={"error": error, "detail": detail},
        )
