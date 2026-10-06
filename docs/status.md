# Актуальный статус ALXPRGS SSO

Обновлено: 2026-10-06T19:01:30.930078+03:00. Продукт 0.2.0, источник версии — VERSION. Рабочая ветка new/documentation-refresh; DOC-REFRESH-01 — done. Изменены только документы; приложение, настройки и зависимости сохранены.

## Реализовано и описано

FastAPI/PostgreSQL 16, React/TypeScript и независимый Python SDK. OIDC Authorization Code + PKCE S256, раздельные access/ID profiles, rotation/replay, server-side sessions и RBAC. Саморегистрация сначала создаёт pending заявку, требует email и актуальных согласий. TOTP/Passkey/Recovery default-off; REQUIRE_VERIFIED_EMAIL регулирует legacy/admin-created вход. Чувствительные действия используют одноразовую повторную аутентификацию; временный admin пароль требует смены.

Compose разделяет owner/migrator/runtime PostgreSQL роли, публикует только loopback3000, head0010_registration_session. SMTP/SES/Resend selectable; Sentry default-off, production Replay hard-off. Privacy включает 14-дневное удаление, audit90d и backup/journal30d. Целевой issuer — проектный адрес; public production deployment не подтверждён.

## Проверено в DOC-REFRESH-01

- 63 Markdown и 13 сопутствующих файлов включены в [реестр](index.md); 56 Settings сопоставлены с Compose/start scripts.
- 357 локальные ссылки/якоря, 4 Python snippets (AST), 16 исторических Git targets — 0 ошибок; UTF-8/fences и whitespace проверены.
- OpenAPI snapshot и связанные static/unit security/build checks: 22 passed в Python3.12.14 (.venv-sentry). Версии и build-lock check PASS; Alembic heads —0010_registration_session.
- Backup/restore/key/e2e CLI --help без операций; 4 brand files совпадают с bytes/SHA-256 manifest.
- Detect-secrets1.5.0 через python -m:129 signals/0new, synthetic control detected, plugins/filters совпадают с baseline. Штатный .exe launcher не работает (uv trampoline); его исходный self-test не объявлен PASS.

Исторические CI/CodeScene/PG/E2E/аудиты сохранены в [acceptance](acceptance.md), [worklog](worklog.md) и ADR. Их PASS относится к указанным SHA, не к нынешнему дереву.

## Не проверено и следующий шаг

Общая production-приёмка остаётся незакрытой. В этой задаче не повторялись PostgreSQL integration, Compose runtime, браузерные E2E, чистая установка нового wheel и live callback, backup/restore, реальные письма, Sentry SaaS, публичный HTTPS/OIF и удалённый CI. До production нужны утверждённая инфраструктура/операторские реквизиты, внешние privacy/provider/ops evidence и owner-review истории секретов.

DOC-DEF-01 воспроизведён на временной копии: bump_version не обновляет npm lock version metadata. Текущие версии0.2.0 совпадают; исправление [DOC-VERSION-LOCK-01](plan.md) planned, код не менялся.

Точка продолжения: review документационного diff; отдельная реализация lock consistency и общая приёмка по [методике](03-test-procedure.md). По новому поручению владельца DOC-REFRESH-PR-01 in_progress: commit/push/PR документации в main. Release/deploy не выполнялись.
