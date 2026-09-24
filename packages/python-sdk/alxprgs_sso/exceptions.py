from __future__ import annotations


class SSOError(Exception):
    """Базовое исключение библиотеки alxprgs-sso."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(SSOError):
    """Ошибка конфигурации клиента SSO."""

    pass


class InvalidTokenError(SSOError):
    """Недействительный или скомпрометированный токен."""

    pass


class TokenExpiredError(InvalidTokenError):
    """Срок действия токена истёк."""

    pass


class InsufficientPermissionsError(SSOError):
    """Недостаточно прав (ролей) для выполнения действия."""

    pass
