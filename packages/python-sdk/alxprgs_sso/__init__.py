from __future__ import annotations

from alxprgs_sso.client import SSOClient
from alxprgs_sso.exceptions import (
    ConfigurationError,
    InsufficientPermissionsError,
    InvalidTokenError,
    SSOError,
    TokenExpiredError,
)
from alxprgs_sso.models import TokenResponse, UserClaims

__version__ = "0.1.0"

__all__ = [
    "SSOClient",
    "UserClaims",
    "TokenResponse",
    "SSOError",
    "ConfigurationError",
    "InvalidTokenError",
    "TokenExpiredError",
    "InsufficientPermissionsError",
]
