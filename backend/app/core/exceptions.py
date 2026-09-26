from __future__ import annotations

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
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": error, "detail": detail},
        )


class AuthorizationException(HTTPException):
    def __init__(self, detail: str = "Недостаточно прав для выполнения действия") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": detail},
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
