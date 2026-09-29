# План тестирования ALXPRGS SSO (GOAL-03)

- **Версия**: 1.0.0
- **Дата создания**: 2026-09-24T18:10:00+03:00
- **Статус**: В работе
- **Базовые документы**: `GOAL.md`, `GOAL-02-registration-and-setup.md`, `GOAL-03-testing-and-fixes.md`, `AGENTS.md`

---

## 1. Стратегия и принципы тестирования

1. **Разделение уровней тестирования**:
   - **Unit-тесты**: Чистая изолированная логика (криптография, парсинг, нормализация, валидаторы схем, генерация PKCE S256). Не требуют базы данных и сети.
   - **Integration-тесты (PostgreSQL)**: Тестирование реальных SQL-запросов, транзакций, блокировок, миграций Alembic, ограничений целостности (unique constraints), rate limiting и аудита на живой изолированной базе данных PostgreSQL. Падают при недоступности PostgreSQL (без скрытых моков и fallback).
   - **Protocol/Security-тесты**: Проверка RFC 6749, RFC 7636 (PKCE), RFC 7519 (JWT), RFC 7009 (Revocation), RFC 6238 (TOTP), W3C WebAuthn Level 3 на реальных HTTP-вызовах.
   - **E2E/Браузерные тесты**: Playwright с реальным бэкендом и фронтендом (SPA Vite + React 18): регистрация, вход, переключение режима в панели администратора, SSO двух клиентов, управление профилем и сессиями.
   - **SDK-тесты**: Сборка `.whl` пакета, установка в изолированное окружение `venv` без доступа к исходникам `backend/`, проверка импортов, FastAPI middleware, клиента и примеров.
   - **Operational/Эксплуатационные тесты**: Чистый запуск Docker Compose, скрипты `start.ps1` / `start.sh`, backup и restore на отдельной БД, ротация ключей.

2. **Профили тестирования**:
   - **Профиль по умолчанию** (`FEATURE_TOTP_ENABLED=false`, `FEATURE_PASSKEY_ENABLED=false`, `FEATURE_RECOVERY_CODES_ENABLED=false`, `FEATURE_EMAIL_VERIFICATION_ENABLED=true`, `REQUIRE_VERIFIED_EMAIL=false`): проверка блокировки трёх MFA-функций (404 feature_disabled), обязательного подтверждения новой самостоятельной регистрации и отсутствия SMTP-трафика при закрытой регистрации.
   - **Enabled профиль** (все 4 флага `true`, `REQUIRE_VERIFIED_EMAIL=true`): сквозные тесты TOTP enrollment/verify/login, WebAuthn регистрация и вход с виртуальным аутентификатором, выпуск и сгорание recovery codes, подтверждение email токенами.

---

## 2. Матрица требований и методов проверки (QA-01 — QA-15)

| QA ID | Область | Связанные требования | Уровень теста | Среда | Команда проверки | Приоритет |
|---|---|---|---|---|---|---|
| **QA-01** | Аудит тестового набора | Section 2 GOAL-03 | Анализ / Инвентаризация | Local | `pytest --collect-only` | P0 |
| **QA-02** | Настоящая PostgreSQL | ARCH-04, SEC, GOAL-02 | Integration | PostgreSQL 16 (Docker) | `pytest tests/integration/ -m postgres` | P0 |
| **QA-03** | Чистая установка | SETUP-01..09 | Operational / E2E | Docker Compose / CLI | `./start.ps1`, `docker compose up` | P0 |
| **QA-04** | Повторный запуск и сбои | SETUP-02, 06, 07, TEST-SETUP-02..04 | Operational / CLI | Docker / Host | `pytest tests/test_bootstrap_admin.py` | P0 |
| **QA-05** | Регистрация | REG-01..08, TEST-REG-01..04 | Integration / API | PostgreSQL 16 | `pytest tests/integration/test_registration_pg.py` | P0 |
| **QA-06** | Пароли, сессии, RBAC | USR-01..09, ARCH-03..05 | Integration / API | PostgreSQL 16 | `pytest tests/integration/test_auth_sessions_pg.py` | P0 |
| **QA-07** | OIDC и 2 клиента | SSO-01..07, SDK-06 | Integration / API | PostgreSQL 16 / HTTP | `pytest tests/integration/test_oidc_pg.py` | P0 |
| **QA-08** | Четыре функции (Default-off & Enabled) | SEC-FLAG-01..07, REG-08..09 | Integration / API | PostgreSQL 16 / WebAuthn | `pytest tests/test_mfa_features.py` | P0 |
| **QA-09** | Конкурентность и гонки | Section 4 (4), REG-06, SETUP-05 | Concurrency | PostgreSQL 16 (pool) | `pytest tests/integration/test_concurrency_pg.py` | P0 |
| **QA-10** | Лимиты и отказоустойчивость | Section 4 (3, 6), REG-07 | Integration / Load | PostgreSQL 16 | `pytest tests/integration/test_rate_limits_pg.py` | P1 |
| **QA-11** | React и браузер (E2E) | UI-01..04, REG-01, TEST-UI-01 | E2E Playwright | Chromium / Headless | `npm run test:e2e` в `frontend/` | P1 |
| **QA-12** | Python SDK в чистой среде | SDK-01..06 | Isolated venv | Clean Wheel Install | `pytest tests/sdk/` в изолированном env | P1 |
| **QA-13** | Миграции и восстановление | ARCH-04, OPS, SETUP-06 | Operational / DB | PostgreSQL 16 | `python scripts/restore_db.py`, alembic | P1 |
| **QA-14** | CI, сборки и релизы | VER-01..03, CI-01..02, REL-01..03, CD-01..03 | CI / Static | Local / GitHub Actions | `ruff`, `tsc`, `bump_version.py`, dry-run | P1 |
| **QA-15** | Документация и полнота | Section 5 GOAL, ЕСПД | Audit / Manual | Docs | Verification checklist | P2 |

---

## 3. Инфраструктура тестового стенда

- **База данных PostgreSQL для интеграционных тестов**:
  - Контейнер Docker: `alxprgs-sso-test-db`
  - Образ: `postgres:16-alpine`
  - Порт: `5433` (чтобы не конфликтовать с production/local портом `5432`)
  - Пользователь: `test_user`
  - Пароль: `test_password_123`
  - База: `alxprgs_sso_test`
- **Тестовый веб-сервер**:
  - Uvicorn / TestClient / httpx.AsyncClient с привязкой к тестовой БД
- **Тестовый E2E стенд**:
  - Backend: `http://127.0.0.1:8000`
  - Frontend: `http://127.0.0.1:3000`
  - Два клиента RP: `http://127.0.0.1:8001`, `http://127.0.0.1:8002`
- **Изолированный venv для SDK**:
  - Путь: `.venv-sdk-test`
