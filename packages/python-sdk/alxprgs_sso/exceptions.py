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


class StepUpError(SSOError):
    """Base error for transaction step-up operations."""

    pass


class StepUpUnavailableError(StepUpError):
    """Feature is disabled or the client is not allowed to use it."""

    pass


class StepUpPolicyError(StepUpError):
    """Requested assurance/action is not permitted by the server policy."""

    pass


class StepUpAuthenticationError(StepUpError):
    """Client authentication or browser-session binding failed."""

    pass


class StepUpRejectedError(StepUpError):
    """Proof is invalid, tampered with, or bound to another transaction."""

    pass


class StepUpExpiredError(StepUpRejectedError):
    """Challenge or proof has expired."""

    pass


class StepUpReplayError(StepUpRejectedError):
    """Proof has already been consumed."""

    pass


class StepUpBindingError(InvalidTokenError):
    """Signed proof does not match the expected issuer/audience/transaction."""
