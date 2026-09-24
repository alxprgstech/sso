# Текущий срез и статус разработки ALXPRGS SSO

## Актуальный срез: Выполнение GOAL-05 (Исправление профилей и E2E) — ИСПРАВЛЕНИЯ ЗАВЕРШЕНЫ, ОЖИДАЕТСЯ УДАЛЁННЫЙ CI

- **Дата актуализации**: 2026-09-25T01:35:00+03:00
- **Исполнитель**: Antigravity
- **Целевой документ**: `GOAL-05-ci-profiles-and-e2e.md`
- **Текущий статус**: TASK-044 (done), TASK-045 (done), TASK-046 (done), TASK-047 (done). Ожидается push и GitHub Actions run.
- **Подтверждённый baseline**: GitHub Actions run `36064941763` — Backend enabled 6 failed/11 passed, Playwright 5 failed/3 passed.
- **Первопричины устранены**: BUG-015, BUG-016, BUG-017 → Fixed.

---

## 1. Статус задач GOAL-05

- **TASK-044 (Диагностика и baseline)**: **done**. Локально воспроизведены все 6 упавших backend тестов и 5 Playwright. Первопричины доказаны и зарегистрированы.
- **TASK-045 (Изоляция профилей backend)**: **done**. Тесты profile-изолированы; 107 passed (default-off) + 17 passed (enabled) без единого fail.
- **TASK-046 (Playwright E2E и WebAuthn)**: **done**. `playwright.config.ts`, `sso.spec.ts`, `passkey.spec.ts`, `scripts/prepare_e2e_data.py` исправлены.
- **TASK-047 (CI workflow)**: **done**. `.github/workflows/ci.yml` разделён на Default-off E2E стенд (`sso.spec.ts`) и Enabled E2E стенд (`passkey.spec.ts`), оба с `WEBAUTHN_RP_ID=localhost`, `WEBAUTHN_ORIGIN=http://localhost:5173`.

---

## 2. Матрица локальных проверок GOAL-05

| Контур | Статус | Метрика |
|---|---|---|
| Backend Default-off pytest (PostgreSQL) | **PASSED** | 107 passed / 0 failed (1:52 мин) |
| Backend Enabled pytest (PostgreSQL) | **PASSED** | 17 passed / 0 failed (54 с) |
| Ruff lint + format check | **CLEAN** | 0 errors, 58 files OK |
| Frontend TypeScript typecheck | **PASSED** | 0 errors |
| Frontend production build | **PASSED** | 199 kB JS, 7.5 kB CSS, 2.5 с |
| SDK build (wheel + sdist) | **PASSED** | alxprgs_sso-0.2.0.whl, .tar.gz |
| SDK isolated venv test | **PASSED** | 3 passed / 0 failed |
| prepare_e2e_data.py (seeding) | **PASSED** | 4 пользователя создано/обновлено |
| Playwright E2E (локально) | **НЕ ЗАПУСКАЛСЯ** | Требует запущенного backend+frontend |

---

## 3. Изменённые файлы GOAL-05

| Файл | Изменение |
|---|---|
| `backend/app/services/mfa_service.py` | settings=None параметр, expected_origins расширен localhost:5173 |
| `backend/app/api/mfa.py` | Передача settings и origin в сервис |
| `tests/test_mfa_features.py` | Изоляция через model_construct() и dependency_overrides |
| `tests/integration/test_passkey_pg.py` | Изоляция default-off теста; REQUIRE_VERIFIED_EMAIL=False в enabled тестах |
| `tests/integration/test_email_verification_pg.py` | Изоляция default-off теста |
| `tests/integration/test_features_pg.py` | Изоляция default-off теста |
| `scripts/prepare_e2e_data.py` | Вызов initialize/verify_test_database_marker перед посевом |
| `frontend/playwright.config.ts` | baseURL → localhost:5173; таймаут 45s/10s |
| `frontend/e2e/sso.spec.ts` | Fail-fast, убран fallback DSN, test.use baseURL |
| `frontend/e2e/passkey.spec.ts` | Fail-fast, убран fallback DSN |
| `.github/workflows/ci.yml` | Разделение E2E на Default-off и Enabled профили; WEBAUTHN_RP_ID, WEBAUTHN_ORIGIN; OIDC_ISSUER; frontend на 0.0.0.0:5173 |

---

## 4. Блокер и минимальное условие разблокировки

- **Блокер**: Отсутствие прямого сетевого доступа к `github.com` из среды выполнения агента для отправки коммита в удалённый репозиторий.
- **Минимальное действие владельца**: Выполнить `git push origin main` из своего терминала (или средствами GitHub Desktop/VS Code). После этого GitHub Actions автоматически выполнит обновлённый CI (`ci.yml`) — backend + Playwright E2E — и при успехе будет предоставлено доказательство удалённого зелёного прогона.

---

## 5. Статус GOAL-04 (закрыт)

25.09.2026: Выполнен `GOAL-04-verification-gaps-and-ci.md`. Все пять целевых областей (G4-DB, G4-EMAIL, G4-PASSKEY, G4-LIMITS, G4-CI) полностью реализованы, дефекты BUG-010..BUG-014 устранены с regression tests, документация обновлена.
