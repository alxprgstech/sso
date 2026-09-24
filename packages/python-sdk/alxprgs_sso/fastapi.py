from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from alxprgs_sso.client import SSOClient
from alxprgs_sso.exceptions import SSOError
from alxprgs_sso.models import UserClaims

http_bearer = HTTPBearer(auto_error=False)


class SSOFastAPISecurity:
    """
    Интеграционный компонент для защиты FastAPI сервисов токенами ALXPRGS SSO (SDK-03).
    """

    def __init__(self, client: SSOClient) -> None:
        self.client = client

    def get_current_user(
        self,
        credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    ) -> UserClaims:
        """
        Зависимость FastAPI для извлечения и валидации Bearer Access Token.
        """
        if not credentials or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer-токен авторизации не предоставлен",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials
        try:
            claims = self.client.verify_access_token(token)
            return claims
        except SSOError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )

    def require_role(self, role: str) -> Callable[[UserClaims], UserClaims]:
        """
        Зависимость FastAPI для проверки наличия необходимой роли (серверный RBAC).
        """

        def _role_checker(user: UserClaims = Depends(self.get_current_user)) -> UserClaims:
            if role not in user.roles and "admin" not in user.roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Для доступа требуется роль '{role}'",
                )
            return user

        return _role_checker
