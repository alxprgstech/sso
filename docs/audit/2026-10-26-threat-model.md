# Threat model текущего аудита (26.10.2026)

Документ уточняет [security.md](../security.md) применительно к проверенной ревизии (`a35550f` + изменения ветки). Это не сертификация ASVS и не заявление о полноте.

## 1. Активы

1. Учётные записи, пароли (Argon2id), TOTP secrets (Fernet), Passkey public keys и counters.
2. Browser sessions (host-only HttpOnly cookie; в БД — SHA-256), MFA assurance (`Session.mfa_verified`/`amr`).
3. OIDC grants: authorization codes, refresh tokens (семейства), access/ID JWT, JWKS private key.
4. Reauthentication proofs (`SecurityAuthorization`) и external step-up proofs.
5. Административные возможности: роли, блокировки, OIDC clients/secrets, режим регистрации.
6. Аудит, privacy/deletion state, notification outbox.
7. CI/release artifacts, lock-файлы, container images.

## 2. Trust boundaries

| Граница | Внешняя сторона | Контроль |
| --- | --- | --- |
| Browser ↔ Nginx/FastAPI | анонимный сетевой атакующий, XSS/CSRF, украденный cookie | TLS на edge, host-only cookie, CSRF HMAC, exact Origin, CSP, rate limits |
| Browser ↔ RP (OIDC) | контролируемый RP, mix-up, code injection | exact redirect URI, state/nonce, PKCE S256, issuer/audience |
| RP backend ↔ `/oauth/token`,`/oauth/revoke` | public/confidential clients, перебор секретов | client auth, source quota до дорогой проверки, rotation + replay detection |
| Browser ↔ external step-up | hostile external client | confidential client auth, action/payload/redirect/session/revision binding, one-use code + PKCE |
| Backend ↔ PostgreSQL | сбой/недоступность БД | fail-closed лимиты, транзакции, row locks, миграции |
| Backend ↔ SMTP/SES/Resend | внешний провайдер | STARTTLS verify, таймауты, без fallback; коды/ссылки одноразовые |
| Operator ↔ runtime | ошибочная конфигурация, утечка secrets | production validation, DB roles, секреты только в окружении |
| CI ↔ supply chain | скомпрометированный пакет/образ/runner | hash-locks, pinned images/actions, pip-audit, npm audit, Trivy, secret scan |

## 3. Акторы и сценарии

- **Анонимный атакующий:** перебор паролей/OTP, перечисление аккаунтов, CSRF, open redirect, подделка forwarded headers, replay кодов/refresh, DoS через дорогие операции.
- **Обычный пользователь:** IDOR на чужие сессии/профиль, повышение роли, обход admin assurance, повторное использование своего TOTP/recovery, обход reauth на мутациях.
- **Администратор (не доверенный к любым входным данным):** last-admin invariant, self-lockout, client policy, XSS через данные, которые он вводит.
- **Владелец украденного cookie/bearer:** доступ к нечувствительным данным, попытка получить assurance/reauth без пароля, использование read grant.
- **Контролируемый RP/внешний клиент:** подмена action/payload/redirect, использование чужого proof, replay после redemption.
- **Скомпрометированный CI/registry:** подмена артефакта, внедрение зависимости, уязвимый базовый образ.

## 4. Ключевые инварианты (проверялись)

1. Cookie-auth mutation требует CSRF + exact Origin; CORS не расширяется.
2. Секрет сессии — случайный, в БД hash; login создаёт новую сессию; revision инвалидирует старые.
3. `security_revision` меняется при password/role/email/factor/recovery событиях; admin API требует live session + RBAC + assurance.
4. Reauth proof: user+session+revision+action+body, 5 минут, одноразовый для mutation; GET /sessions — отдельный переиспользуемый read grant на 5 минут.
5. TOTP: подтверждённый шаг строго больше предыдущего; row lock; один код = одна операция.
6. Recovery code: hash, одноразовый, только после подтверждённого фактора, не даёт strict assurance.
7. OIDC: code одноразовый, PKCE S256, refresh rotation + family replay, ID token не принимается вместо access token.
8. Step-up: feature/per-client opt-in, confidential client, one-use redemption, binding к актуальной session/revision/redirect.
9. Fail-closed при недоступности БД для лимитов и чувствительных операций.
10. Секреты и PII не попадают в логи/аудит/Sentry; arbitrary payloads запрещены.

## 5. Остаточные риски (приняты/вне scope)

- Offline access JWT у автономного RP действует до `exp` (≤300 с); мгновенный отзыв не гарантируется.
- Кража cookie даёт доступ к данным без повторного фактора до истечения сессии; reauth защищает только чувствительные операции.
- Read grant просмотра сессий хранится в tab-scoped `sessionStorage` (см. ADR-0033): XSS в том же origin может его прочитать в пределах 5 минут; список сессий не содержит секретов, mutation-proof не хранится.
- Общий NAT разделяет source-квоты; распределённый флуд требует edge/bot admission.
- Компрометация runner/signing key/БД разрушает базовые допущения.
- Windows-стенд не воспроизводит psql/pg_dump-зависимые проверки; они выполняются в Linux CI.
