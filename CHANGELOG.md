# История изменений (Changelog) ALXPRGS SSO

Все заметные изменения в проекте ALXPRGS SSO документируются в этом файле.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/), и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

---

## [Unreleased]

### Изменено
- MFA default-on: TOTP, Passkey и Recovery codes доступны без ручных env-переменных; explicit-disabled профиль сохранён для диагностики/fail-closed. `REQUIRE_ADMIN_MFA=true` по умолчанию.
- Административный доступ требует server-side session assurance (`Session.mfa_verified`/`mfa_method`/`amr`) и fresh подтверждения фактора; password-only/legacy сессии не получают admin API. Первый администратор проходит защищённый onboarding.
- Recovery codes выпускаются при TOTP **или** Passkey после fresh reauthentication, остаются одноразовыми и не дают phishing-resistant assurance.
- OIDC access/ID tokens получают `amr`/`acr`; admin-роль не выдаётся grant без assurance; старые refresh grants остаются non-assured.
- Новая миграция `0016_session_assurance`; EC2 `ssoctl mfa-status`/`enable-mfa` для non-destructive проверки и targeted изменения конфигурации.
- Frontend: защищённый `/admin` onboarding с Passkey/TOTP и elevation; состояние MFA в `/account/security`.
- Аудит 26.10.2026: пятиминутный grant просмотра сессий сохраняется в tab-scoped `sessionStorage` (с серверным TTL) и переживает reload; mutations его не используют. Повторный TOTP-шаг возвращает `401 totp_code_reused` + `Retry-After`, не считается неверной попыткой; UI показывает countdown и пояснение одноразовости. Reauth-диалог ставит конкурентные операции в очередь. Смена режима регистрации подтверждается один раз: action-bound proof (пароль + MFA), legacy-поле `current_admin_password` необязательно. RBAC admin API проверяется до reauth-челленджа.
- Зависимости: setuptools 84.1.0, filelock 4.2.1, vitest 5.0.5, jsdom 30.1.3, @sentry/cli 3.8.2, транзитивные next/undici обновлены; frontend image на nginx 1.30.6-alpine с apk upgrade (0 HIGH/CRITICAL по Trivy).

### Добавлено
- Тесты: admin MFA onboarding/legacy session/role grant/last-factor, OIDC assurance/refresh/UserInfo, Passkey-only recovery, default-on/explicit-disabled матрица, EC2 config commands.
- ADR-0032 (default-on MFA, admin policy, recovery и session assurance); ADR-0004 сохраняет историю и ссылается на superseding decision.
- Аудит-регрессии: TOTP replay через login/reauth и конкурентные подтверждения, registration-mode proof без второго пароля, порядок RBAC/reauth для admin API, read-grant через reload, очередь reauth-диалога, viewport 375 в appearance.
- Отчёты аудита `docs/audit/2026-10-26-*` и ADR-0034.

## [0.3.0] - 2026-10-26

### Добавлено
- Cross-application transaction step-up: hosted подтверждение конкретной операции для доверенных confidential OIDC clients, password/TOTP/Passkey и комбинированные политики, transaction binding, одноразовый proof с server-side redemption, отдельный JWT `external_step_up_proof`, SDK API и reference RP (`examples/step_up_rp.py`). Новая возможность `FEATURE_EXTERNAL_STEP_UP_ENABLED=false` и per-client policy выключены по умолчанию; требуется миграция `0015_external_step_up`. Архитектура — ADR-0031.
- Frontend: страница `/step-up/{token}` с отображением доверенного приложения, операции, assurance и TTL; последовательное подтверждение факторов, Passkey, отмена без выдачи proof, ошибки и доступность.
- SDK 0.3.0: `create_step_up_request`, `build_step_up_url`, `consume_step_up_proof`, типизированные `StepUpRequest`/`StepUpProof`, проверка issuer/audience/sub/action/payload/acr/amr/nonce и отдельные step-up exceptions.
- Admin API/UI: per-client `step_up_enabled`, assurance levels, actions и max TTL; миграция оставляет всех существующих клиентов выключенными.
- Тесты: policy matrix, PostgreSQL lifecycle/replay/concurrency/cross-client/session/security-revision, SDK contract и StepUpPage component.

### Развёртывание EC2

- По прямому запросу владельца добавлен ручной CD из main без успешного общего CI; автоматический CI gate и обязательные transport-проверки сохранены.

- Установка Ubuntu 26.04 amd64 с nginx/Let’s Encrypt и постоянной защищённой конфигурацией.
- По решению владельца активирован код push-main CD после успешного CI точного SHA; образы доставляются по SSH без registry.
- Локальные backup на 30 дней, проверка SHA-256, Resend alerts, обслуживание и ограниченный rollback приложения без автоматического восстановления БД.
- Совпадение имён backup/journal не удаляет существующие копии; очищаются только файлы текущего запуска, перед успехом выполняется fsync.
- Реальное развёртывание и внешняя приёмка выполняются владельцем по `docs/ec2-deployment.md`.

### Исправления аудита безопасности

- Gmail action требует независимый секрет письма; resend инвалидирует прежний секрет. Google JWKS имеет общий bounded cache, single-flight, запрет redirects и лимит 64 KiB.
- Канонические Passkey IDs и exact indexed lookup; миграция отказывается от коллизий без удаления credentials.
- Просмотр своих сессий требует password/configured MFA grant на пять минут; каждый отзыв требует отдельного одноразового proof.
- Успешная смена пароля закрывает форму без неявного запроса защищённого списка сессий; его загрузка требует явного перехода и отдельного подтверждения.
- **Несовместимое изменение SDK:** HTTPS default, `verify_ssl=False` запрещён; для HTTP localhost/loopback явно задавайте `transport_profile="local"`.
- Hash-checked Python installations, release SBOM и неподписанная local build provenance; notifications через transactional PostgreSQL outbox.
- Windows key generator удаляет сторонние explicit ACE до записи ключей; backup ACL validator не зависит от загрузки модулей PowerShell.
- Runtime frontend image: исправленные Alpine `libexpat` 2.9.0-r0 и `tiff` 4.7.2-r0; порог Trivy High/Critical сохранён.
- Cookie Origin/Referer allowlist, строгие redirect URI и owner-only backup files. Требовались миграции 0011…0013; исправления вошли в 0.2.0.

### Конфиденциальность и доступность

- Публичные проектные политики и отдельное согласие; серверная проверка версий при регистрации и входе, gate для SSO.
- Добровольная диагностика, отдельный staging Replay, browser choice на 180 дней и отзыв между вкладками.
- Заявка на удаление через 14 дней, отмена до срока и повторная заявка через 7 дней; повторная парольная/MFA-аутентификация и ограниченная сессия.
- PostgreSQL worker, защита последнего администратора, минимизация геолокации/User-Agent, audit 90 дней и backup/journal 30 дней; restore со свежим журналом.
- Клавиатурная навигация, фокус диалогов, подписи и QR accessibility. Требуется миграция 0004_privacy; юридические тексты остаются проектными.

### Web-интерфейс

- Системная, светлая и тёмная темы всех страниц SSO и обоих demo; локальное сохранение, вкладки и раннее применение без inline scripts.
- Cookies у нижней границы с отдельной областью прокрутки; одинаковое оформление действий согласия и заметный запрет удаления последнего администратора.
- Mouse/label focus пароля проверяется на desktop/mobile; добавлены autofill names, контрастные семантические цвета и мобильные переносы навигации/admin tabs.
- Политика cookies 2026-10-03.1 объясняет функциональное хранение темы.

### Наблюдаемость

- Sentry errors/static traces с allowlist очисткой, default-off runtime flags и публичным frontend config endpoint.
- React ErrorBoundary, типизированные API errors и staging-only Replay с локальным worker; production Replay выключен.
- Общая VERSION/SHA identity, Debug IDs/private source maps и изолированный release upload без активного CD.
- Безопасные access/application logs, скрытие SQL parameters и отсутствие сырых readiness exception messages.

### Безопасность и ядро OIDC
- Обязательная аутентификация конфиденциальных клиентов по типу клиента в OIDC операциях (FINAL-01).
- Строгая проверка сессии и блокировки пользователя при авторизации (FINAL-02).
- Интеграция Authlib для Authorization Code + PKCE S256 и фильтрация claims по запрошенным scopes (FINAL-11).
- Ограничение абсолютного срока жизни семейств refresh-токенов (30 дней) и ротация RSA-ключей подписи с kid и окном перекрытия в JWKS (FINAL-11).
- Валидация redirect_uri и return_to для защиты от Open Redirect (FINAL-04).

### Python SDK и SSO-клиенты
- Строгая верификация JWT в SDK с проверкой token_use, audience и кэшированием JWKS (FINAL-03).
- Полноценные веб-хелперы `start_authorization`, `handle_web_callback`, `create_logout_url` и модель `WebSessionInfo` (FINAL-06).
- Безопасные демонстрационные клиенты `client1` и `client2` с HttpOnly сессиями и сквозной E2E тест `multi_client_sso.spec.ts` (FINAL-09).

### Пользовательский интерфейс (Frontend)
- Полноценные UI-компоненты управления TOTP, однократного выпуска кодов восстановления и подтверждения email при включенных флагах (FINAL-05).
- Устранение заглушек MFA на странице входа с поддержкой Passkey (FINAL-05).
- Фильтрация журнала аудита по событиям и IP адресам в панели администратора.

### CI/CD, Сборка и Релизы
- Фиксация воспроизводимых зависимостей Python в `requirements-lock.txt` (FINAL-08).
- Статический тайпчекинг Mypy, расширение Ruff и автоматический сканер секретов и зависимостей `scripts/scan_secrets_and_deps.py` (FINAL-08).
- Безопасный процесс подготовки релизов в GitHub Actions с чтением версии из точного commit SHA, draft-режимом и проверкой целостности артефактов (FINAL-07).

## [0.2.0] - 2026-09-24

### Добавлено
- Самостоятельная регистрация обычных пользователей (`POST /api/v1/auth/register`, React-страница `RegisterPage.tsx`, адаптивная ссылка на входе при открытом режиме).
- Модель состояния системы `SystemConfiguration` в PostgreSQL (singleton `id=1`, ADR 0005) с контролем `bootstrap_completed` и политики `registration_mode` (`closed` по умолчанию / `open`).
- Административная вкладка конфигурации системы на `AdminPage.tsx` с переключением режима регистрации и подтверждением пароля администратора (re-auth, REG-02).
- Межпроцессное ограничение частоты запросов регистрации (rate limiting) через аудит PostgreSQL и скользящее окно в памяти.
- Скрипты первичного запуска `./start.ps1` (PowerShell) и `./start.sh` (Bash) с автоматической безопасной генерацией `.env` без перезаписи, проверкой Docker/Compose и портов (SETUP-01..04).
- Интерактивный терминальный мастер `bootstrap_admin.py` со скрытым вводом пароля (`getpass`), выбором режима регистрации, запретом повышения существующих пользователей (SETUP-06) и безопасной идемпотентностью (SETUP-05).
- Изоляция портов Compose на loopback (`127.0.0.1:3000:80`) и закрытие порта PostgreSQL (5432) от внешнего доступа (SETUP-08).
- Миграция базы данных Alembic `0002_registration_and_system_configuration.py` с сохранением существующих аккаунтов.
- Комплексный набор тестов `tests/test_registration.py` и `tests/test_bootstrap_admin.py` (19 тестов).

---

## [0.1.0] - 2026-09-24

### Добавлено
- Начальная архитектура и каркас проекта ALXPRGS SSO.
- Документация требований, модели данных, модели угроз и профиля стандартов ЕСПД (ГОСТ 19).
- Единый источник версий (`VERSION`) и автоматизированный инструмент синхронизации версий `scripts/bump_version.py`.
- Пайплайны автоматической непрерывной интеграции (CI) и подготовки релизов в GitHub Actions.
- Закомментированный шаблон непрерывного развёртывания (CD) в `deploy/github-actions/cd.yml.example`.
- Сервер аутентификации на базе FastAPI с поддержкой OpenID Connect (OIDC Core 1.0, PKCE S256).
- Хранение учетных данных в PostgreSQL: хеширование паролей Argon2id, безопасные серверные сессии с Host-Only cookies.
- Полная реализация четырех отложенных возможностей с отключением по умолчанию: TOTP, Passkey (WebAuthn), Recovery codes, верификация email.
- Клиентская библиотека Python SDK `alxprgs-sso` с FastAPI-зависимостью и помощником входа через веб-интерфейс.
- Демонстрационные клиенты OIDC для проверки сквозного единого входа (SSO).
- Пользовательский интерфейс и административная панель на React + TypeScript.
