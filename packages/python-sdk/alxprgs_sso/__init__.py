from __future__ import annotations

from alxprgs_sso.client import SSOClient
from alxprgs_sso.exceptions import (
    ConfigurationError,
    InsufficientPermissionsError,
    InvalidTokenError,
    SSOError,
    TokenExpiredError,
)
from alxprgs_sso.models import TokenResponse, UserClaims, WebSessionInfo

__version__ = "0.2.0"

__all__ = [
    "SSOClient",
    "UserClaims",
    "TokenResponse",
    "WebSessionInfo",
    "SSOError",
    "ConfigurationError",
    "InvalidTokenError",
    "TokenExpiredError",
    "InsufficientPermissionsError",
]
