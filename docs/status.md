# Текущий срез и статус разработки ALXPRGS SSO

## Актуальный срез: Выполнение GOAL-06 (Исправление переключения стендов E2E и строгий Passkey lifecycle) — ЛОКАЛЬНЫЙ ПРОГОН 100% УСПЕШЕН, ПОДГОТОВКА К COMMIT И REMOTE CI

- **Дата актуализации**: 2026-09-25T05:05:00+03:00
- **Исполнитель**: Antigravity
- **Целевой документ**: `GOAL-06-passkey-e2e-runtime.md`
- **Текущий статус**:
  - TASK-050: **done** (воспроизведение и эмпирическое подтверждение гипотезы зомби-процесса uvicorn, BUG-018)
  - TASK-051: **done** (устранение ослаблений WebAuthn: UV строго обязателен, strict origin, удален fallback RP ID, BUG-019)
  - TASK-052: **done** (управление процессами `manage_test_server.py`, 4 теста жизненного цикла, fail-fast preflight capabilities, BUG-020, BUG-021)
  - TASK-053: **done** (единый раннер `run_e2e_suite.py`, 8/8 реальных тестов в Chromium — 4 SSO + 4 Passkey, BUG-022)
  - TASK-054: **done** (полный регрессионный прогон: 112 pytest, 22 MFA/PG, 4 lifecycle, 3 SDK, npm build, npm typecheck, ruff, `docs/acceptance-goal-06.md`)
  - TASK-055: **in_progress** (фиксация коммита, push, подтверждение GitHub Actions CI на финальном SHA)

---

## 1. Детализация статуса задач GOAL-06

| Задача | Область | Статус | Результат / Доказательство |
|---|---|---|---|
| **TASK-050** | Runtime Lifecycle Investigation | **done** | Экспериментально доказано: compound shell в bash оставляет зомби-uvicorn при `kill $!`. При запуске нового профиля uvicorn падает с port collision, старый процесс отвечает на `/capabilities`. Зарегистрирован BUG-018. |
| **TASK-051** | WebAuthn Strict Security | **done** | Устранены ослабления WebAuthn: `UserVerificationRequirement.REQUIRED`, `require_user_verification=True`, strict origin из конфигурации, удален fallback RP ID. Добавлен регрессионный тест в `tests/integration/test_passkey_pg.py` (10 passed). |
| **TASK-052** | Process Daemon & Preflight | **done** | Создан `scripts/manage_test_server.py`. Исправлен Windows SelectorEventLoop для psycopg. Написаны 4 теста `tests/test_server_lifecycle.py` (4 passed). Добавлен fail-fast preflight в E2E спеки и CI. |
| **TASK-053** | Chromium E2E Passkey & SSO | **done** | Создан `scripts/run_e2e_suite.py`. Устранена проблема лимита регистрации в `prepare_e2e_data.py`. Запуск в реальном Chromium: 4 SSO passed + 4 Passkey passed = **8 passed из 8 (100%)**. |
| **TASK-054** | Full Regression & Acceptance | **done** | 112 pytest unit/integration passed; 22 MFA/PG passed; 4 lifecycle passed; 3 SDK clean install passed; npm typecheck OK; npm build OK; ruff OK. Составлен акт `docs/acceptance-goal-06.md`. |
| **TASK-055** | Commit & Remote CI Verification | **in_progress** | Подготовка коммита, выполнение git push, отслеживание CI run на финальном commit SHA. |

---

## 2. Сводная матрица проверок GOAL-06

| Контур / Инструмент | Статус | Метрика / Результат | Время выполнения |
|---|---|---|---|
| **Playwright Chromium E2E (SSO Suite)** | **PASSED** | 4 passed / 0 failed (default-off: login, session, admin, logout) | 10.3 с |
| **Playwright Chromium E2E (Passkey Suite)** | **PASSED** | 4 passed / 0 failed (enabled: capabilities, 2 credentials, login, delete) | 13.1 с |
| **Server Lifecycle Suite (pytest)** | **PASSED** | 4 passed / 0 failed (`test_server_lifecycle.py`) | 6.84 с |
| **Backend Integration & Unit (pytest)** | **PASSED** | 112 passed / 0 failed (PostgreSQL 16) | 59.09 с |
| **MFA & Feature Flags Suite (pytest)** | **PASSED** | 22 passed / 0 failed (strict WebAuthn, email, TOTP, recovery) | 54.12 с |
| **Python SDK Clean Install Suite** | **PASSED** | 3 passed / 0 failed (чистая среда venv, wheel) | 0.49 с |
| **Frontend TypeScript Typecheck** | **PASSED** | 0 errors (`npx tsc --noEmit`) | 1.1 с |
| **Frontend Production Build** | **PASSED** | 0 errors (Vite build, 199 kB bundle) | 962 мс |
| **Python Linter & Formatter** | **PASSED** | 0 errors (`ruff check .`) | 0.2 с |

---

## 3. Зарегистрированные и устраненные дефекты GOAL-06

| ID дефекта | Описание | Статус | Устранение |
|---|---|---|---|
| **BUG-018** | Фоновый compound shell в CI оставлял uvicorn-зомби на порту 8000 | **Fixed** | Управление через `scripts/manage_test_server.py` с записью точного PID процесса ОС. |
| **BUG-019** | Ослабления WebAuthn (`require_user_verification=False`, dynamic origin, fallback RP ID) | **Fixed** | Установлен строгий `UserVerificationRequirement.REQUIRED`, `require_user_verification=True`, strict origin из настроек, исключен fallback RP ID. |
| **BUG-020** | Отсутствие fail-fast preflight перед E2E приводило к каскадным 45с таймаутам | **Fixed** | Команда `preflight` в `manage_test_server.py` и хуки `beforeAll` в Playwright спеках. |
| **BUG-021** | Uvicorn 0.36.0+ ProactorEventLoop на Windows ломал psycopg async connection | **Fixed** | Принудительная установка `SelectorEventLoopPolicy` и параметра `--loop asyncio:SelectorEventLoop`. |
| **BUG-022** | Повторные E2E прогоны падали с HTTP 429 из-за остаточных записей аудита регистрации | **Fixed** | Очистка таблицы `audit_events` и тестовых пользователей в `prepare_e2e_data.py`. |

---

## 4. Следующие шаги

1. Зафиксировать все изменения и документацию в Git с подробным описанием решения GOAL-06.
2. Выполнить `git push origin main`.
3. Отследить удаленный запуск GitHub Actions CI по commit SHA.
4. При успешном завершении всех шагов CI зафиксировать ссылку на run и подтвердить выполнение контракта `GOAL-06-passkey-e2e-runtime.md`.
