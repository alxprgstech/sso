# Подготовка и запуск проверок

Продукт 0.2.0; команды сверяются с `.github/workflows/ci.yml`, `pytest.ini`, manifests и существующими runner-скриптами. Документ не является новым актом приёмки.

## Среда

CI использует Python 3.12 и Node.js 24; backend image — Python 3.13.16, PostgreSQL — 16. Устанавливайте `requirements-lock.txt` в отдельную Python-среду, frontend — через `npm ci`. Полный requirements-lock.txt включает build/setuptools/wheel; requirements-build-lock.txt — сокращённый набор backend builder, его одного недостаточно для setuptools-сборки SDK. В Windows предпочтителен `PYTHONUTF8=1`.

Интеграция требует отдельной синтетической PostgreSQL. `TEST_DATABASE_URL` экспортируется явно, не извлекается guard из dotenv. Guard проверяет допустимое имя, выделенную цель и существующий marker до очистки таблиц. Не используйте рабочую Compose БД и не создавайте marker на существующей базе. [Эксплуатация тестовой БД](../operations.md) и `scripts/init_fresh_ci_test_marker.py --help` описывают условия fresh/local-fresh; fixture не создаёт marker автоматически.

## Python и SDK

Из корня после подготовки среды:

```text
python -m pytest tests/ -v
python -m pytest tests/test_documented_api_contract.py -q
python scripts/bump_version.py check
python scripts/build_lock.py --check
```

Первый запуск включает настоящие PostgreSQL-тесты. Обычный pytest исключает внешнюю email-группу. Для выбранных unit-проверок без БД используйте точный перечень файлов и `-m "not postgres"`; это не полная приёмка.

[SDK](../sdk.md) собирается wheel/sdist, устанавливается в новую среду и проверяется без подмены пакета исходниками через PYTHONPATH. CI запускает изолированные тесты пакета и проверки JWKS. Live callback двух клиентов — отдельная браузерная проверка, а не unit SDK.

## Frontend и браузер

Из `frontend/`:

```text
npm ci
npm run lint
npm run typecheck
npm run typecheck:tests
npm run test:unit
npm run test:components
npm run build
```

Production source build требует проверенного `ALX_BUILD_SHA`. Для Windows: `$env:ALX_BUILD_SHA = git rev-parse HEAD`; Bash: `export ALX_BUILD_SHA=$(git rev-parse HEAD)`.

Реальный runner из корня: `python scripts/run_e2e_suite.py --suite all`. Он готовит управляемый тестовый стенд; предварительно нужны guarded PostgreSQL, установленные зависимости и Chromium. `--suite sso` и `--suite passkey` выбирают сценарии; `--suite email` отдельно отправляет реальные письма и требует соответствующего поручения/credentials.

Default-off и enabled проверяются отдельно. Email обязателен в обоих; enabled включает TOTP/Passkey/Recovery с точным origin/RP и настоящим virtual authenticator с UV. Appearance fixtures проверяют UI; CSP проверяется за Nginx. Ни fixtures, ни build не подтверждают реальный вход.

## Внешние проверки и результат

[Email](email.md) требует SES/testmail и отдельного opt-in. Обычный main CI вправе пропустить группу без AWS credentials; явный `run_email_tests=true`, включая release, требует её успеха. [Sentry](../observability.md), публичный HTTPS, OIF, production backup/restore и owner-review имеют отдельные внешние критерии.

Записывайте SHA, версии среды, профиль, команды, результаты и ограничения в [приёмку](../acceptance.md). Исторические результаты не переносятся на новую ревизию. Полная программа — [методика](../03-test-procedure.md), ручные сценарии — [чек-лист](manual-checklist.md).
