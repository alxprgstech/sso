# ADR-0032: MFA по умолчанию, обязательная MFA администратора и session assurance

Статус: принято 26.10.2026. Заменяет действовавшую default-off часть [ADR-0004](0004-feature-flags-and-mfa-policy.md). Дополняет, но не заменяет [ADR-0031](0031-external-transaction-step-up.md) (внешний step-up остаётся независимой opt-in политикой) и [ADR-0015](0015-security-revision-and-reauth.md).

## Контекст

Владелец изменил продуктовую политику: TOTP, Passkey и Recovery codes должны быть доступны при обычной установке и production-развёртывании без ручного включения переменных. Одновременно административный доступ должен требовать реально выполненного второго фактора, а не только роли, cookie или `auth_time`. Прежняя модель хранила `Session.auth_time` и `security_revision`, но не имела отдельного серверного признака MFA; OIDC grants также не сохраняли assurance.

Ограничения: production нельзя менять без отдельного разрешения; существующий `runtime.env` нельзя перезаписывать или перегенерировать; аккаунты с настроенными факторами нельзя понижать до password-only; внешний step-up нельзя включать автоматически; recovery codes нельзя привязывать только к TOTP; старые сессии/grants не должны получить административные права после обновления.

## Решение

### 1. Конфигурация

`Settings` использует `FEATURE_TOTP_ENABLED=true`, `FEATURE_PASSKEY_ENABLED=true`, `FEATURE_RECOVERY_CODES_ENABLED=true`, `REQUIRE_ADMIN_MFA=true`. Отсутствие переменных сохраняет эти значения. Явный `false` остаётся аварийным переключателем. Recovery требует хотя бы один из TOTP/Passkey; `REQUIRE_ADMIN_MFA=true` при обоих выключенных факторах отвергается startup validation, чтобы не создать неявную блокировку администраторов. `.env.example`, Compose, `start.sh`/`start.ps1`, EC2 `ssoctl configure` и проверочные скрипты приведены к default-on. Для существующего EC2 добавлены read-only `mfa-status` и targeted `enable-mfa` (private backup, только четыре ключа, без перезапуска и без изменения секретов).

### 2. Session assurance

`Session` получает `mfa_verified`, `mfa_method` (`totp`/`passkey`/`recovery_code`), `mfa_verified_at` и `amr`. Значения пишет только сервер после успешной проверки фактора. Парольный вход создаёт `mfa_verified=false`. MFA-вход TOTP/Passkey/Recovery создаёт assured-сессию. Onboarding-сессия администратора имеет `purpose=admin_mfa_enrollment` и доступ только к `me/logout/legal`, настройке TOTP/Passkey, управлению собственными passkey, reauthentication и `POST /api/v1/auth/session/elevate`. После настройки фактора пользователь подтверждает его fresh proof в этой же сессии; только тогда `purpose=full` и `mfa_verified=true`. `invalidate_security_state` очищает assurance сохранённой сессии при изменении факторов, кроме случаев, где вызывающая операция уже проверила fresh factor (выпуск recovery codes).

`auth_time` не считается доказательством. Старые сессии после миграции `0016_session_assurance` имеют `false`. Роль/фактор меняются через `security_revision`, которая отзывает остальные сессии и grants; новая роль не повышает assurance старой сессии.

### 3. Административный доступ

`require_admin_user` проверяет live session, `is_superuser || role=admin` и `Session.mfa_verified`. Без assurance API возвращает `403 admin_mfa_required`; onboarding-сессия на защищённых путях получает `401 admin_mfa_enrollment_required`. Первый bootstrap-администратор проходит обычный onboarding: пароль → TOTP/Passkey → fresh proof → admin. Существующие password-only администраторы после обновления также попадают в onboarding.

### 4. OIDC

`AuthorizationCode` и `RefreshToken` хранят assurance snapshot (`mfa_verified`, `amr`). Access/ID tokens получают `amr` и `acr` (`urn:alxprgs:acr:pwd`/`urn:alxprgs:acr:mfa`). Роль `admin` не выдаётся grant без требуемого assurance; refresh не повышает assurance; UserInfo фильтрует admin по `amr` токена. Существующие refresh tokens после миграции имеют `false`, поэтому не могут получить admin-роль. Access tokens прежней ревизии живут до 300 секунд. Внешний step-up (`FEATURE_EXTERNAL_STEP_UP_ENABLED`/per-client policy) не включается и не расширяется.

### 5. Recovery

Выпуск кодов разрешён при подтверждённом TOTP **или** Passkey, только после fresh reauthentication и только при включённом recovery flag. Хранятся SHA-256-хеши; каждый код одноразовый, погашается атомарным `UPDATE ... RETURNING`; повторный выпуск удаляет прежний набор. Код показывается один раз, не попадает в логи/telemetry. Recovery code может заменить второй фактор после пароля в обычной MFA-политике, но не удовлетворяет `reauth_strict`/Passkey-only assurance и не участвует в external step-up. Наличие только recovery codes не делает аккаунт MFA-required.

### 6. Совместимость

- OIDC Authorization Code + PKCE, refresh rotation/replay, UserInfo, logout и внутренний `X-Reauthentication` сохранены.
- Внешний step-up не включается автоматически; его assurance-модель не дублируется.
- SDK не требует новых публичных методов: добавленные claims совместимы, роли уже фильтруются сервером. SDK не трактует роль как MFA и не повышает assurance.
- Python SDK/backend/frontend используют прежние SemVer/release metadata; публикация и tag не выполняются.

## Альтернативы

1. **Только изменить три boolean default.** Отклонено: не решает admin bypass, session assurance, recovery, старые grants и production migration.
2. **Флаг в `User`/роль «mfa_required».** Отклонено: не доказывает факт проверки в конкретной сессии; клиент/БД могли бы ложно повысить assurance.
3. **Считать passkey-логин всегда transaction authorization.** Отклонено: обычная аутентификация и action-bound step-up — разные уровни; step-up сохраняет отдельную политику.
4. **Одна общая assurance-система с внешним step-up.** Отклонено: разные субъекты/сроки/назначение; общим остаётся понимание методов и UV, но не grants.
5. **Разрешить recovery только при TOTP.** Отклонено: неудобно для Passkey-only и противоречит решению владельца.
6. **Автоматически перезаписывать `runtime.env` при деплое.** Отклонено: риск потери секретов/конфигурации. Вместо этого — статус, backup и targeted update.

## Последствия

- Все существующие сессии и OIDC grants становятся non-assured после миграции; администраторы проходят onboarding. Это осознанная цена.
- Требуется миграция `0016_session_assurance`; rollback удаляет onboarding-сессии и assurance-колонки, но не повышает их.
- Явный `false` не даёт admin bypass для аккаунта с настроенным фактором, но при обоих выключенных факторах требует явного `REQUIRE_ADMIN_MFA=false`.
- Legacy access JWT до 300 секунд и offline RP behavior остаются остаточным риском; refresh/новые grants защищены.
- Live production rollout, backup/restore, внешний OIDC/SDK review и multi-replica проверки остаются отдельной приёмкой.

## Проверки

`test_admin_mfa_pg.py` (onboarding, legacy session, role grant, last-factor deletion, session binding), `test_mfa_assurance_pg.py` (OIDC amr/acr/role suppression, refresh, UserInfo, Passkey-only recovery), `test_features_pg.py` (default-on и explicit-disabled), `test_mfa_features.py`/`test_config` (defaults/validation), `test_reauthentication_pg.py`, `test_passkey_pg.py`, `test_concurrency_pg.py`, `test_oidc_pg.py`, `test_external_step_up_pg.py`, frontend `AdminMfaPage.component.test.tsx`, `test_component` suite, Ruff/mypy, PostgreSQL integration и E2E. Adversarial self-audit и точные результаты — в итоговом отчёте задачи; production-приёмка не заявляется.
