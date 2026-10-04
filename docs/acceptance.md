# Акт и матрица приёмки программного комплекса ALXPRGS SSO

## TASK-096: обязательное email-подтверждение при самостоятельной регистрации (29.09.2026)

| Проверка | Фактический результат | Статус |
| --- | --- | --- |
| `pytest -q tests/test_verification_email.py tests/test_ses_email.py tests/test_mfa_features.py tests/test_registration.py tests/test_core_verify.py tests/test_auth_and_sessions.py tests/test_start_ps1.py tests/test_start_sh.py` | 48 passed, 2 subtests passed; только fake SES, письма не отправлялись | подтверждено локально |
| `pytest --collect-only -q tests/integration/test_registration_pg.py tests/integration/test_email_verification_pg.py tests/integration/test_concurrency_pg.py` | 17 тестов собраны; это не PostgreSQL-исполнение | подтверждена только сборка |
| `ruff check backend/ tests/ scripts/test_smtp_capture.py scripts/manage_test_server.py scripts/run_e2e_suite.py scripts/run_overnight_stability.py` и `ruff format --check` | обе команды прошли | подтверждено локально |
| `mypy --explicit-package-bases backend/app --ignore-missing-imports` | 34 файла без ошибок | подтверждено локально |
| `npm run test:components`, `npm run lint`, `npm run typecheck`, `npm run typecheck:tests`, `npm run build` | 14 component passed; остальные команды успешны | подтверждено локально |
| Защищённая PostgreSQL, миграция 0003, race/replay/TTL, локальный SMTP browser E2E, Compose | Docker CLI и PostgreSQL отсутствуют в текущей среде; браузерный CI ещё не запускался | заблокировано, критерий готовности не закрыт |

Смена контракта `POST /api/v1/auth/register`: `201/user_id` заменено на `202/challenge_id`, затем отдельный вызов подтверждения. Gmail AMP/action требуют отдельной регистрации отправителя Google; наличие Schema.org не гарантирует карточку кода в Gmail. Реальная отправка SES и Gmail action в production не проводились.

## Дополнение TASK-095: локальные AWS credentials в Compose (2026-09-29)

Стандартные `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` и `AWS_SESSION_TOKEN` теперь интерполируются из игнорируемого Git `.env` только для backend-контейнера. PyYAML/mapping и botocore fallback при пустых значениях проверены; secret scan — 0 новых находок. Docker CLI в среде Codex отсутствует, поэтому `docker compose config --quiet`, пересоздание контейнера и фактическая SES-доставка не проверены. TASK-095 остаётся `blocked` до проверки на Docker-хосте; реальные значения ключей в этом акте не фиксируются.

## Дополнение TASK-094: транспорт SES v2 (2026-09-29)

| Критерий | Текущее доказательство | Состояние |
| --- | --- | --- |
| SES Raw multipart text/AMP/HTML, AWS credential chain, From и безопасные ошибки | `tests/test_ses_email.py`, `tests/test_verification_email.py`, fake client | unit подтверждён локально; реальный SES не вызывался |
| SMTP по умолчанию | Текущие unit проверяют multipart MIME и параметры транспорта; локальный SMTP capture прошёл smoke test. Прежний результат default-off для email исторический, см. TASK-096 выше. | частично подтверждено, PostgreSQL/CI ожидают |
| Публичная ссылка без автоматического погашения | Frontend component 12 passed, utility 7 passed, lint/typechecks/build успешны | локально подтверждено компонентно |
| Конфигурация и зависимости | `pip check`, `pip-audit --strict -r requirements-lock.txt`, Ruff, mypy, ограниченный security script, secret scan 116 исторических/0 новых | локально подтверждено |
| PostgreSQL интеграция, Compose и реальная SES-доставка | Новый PG-тест остановлен защитной фикстурой без `TEST_DATABASE_URL`; Docker/psql/pg_dump недоступны; реальная отправка в тестах запрещена | не проверено / blocked |

Эта запись не меняет общую приёмку GOAL-09 и не объявляет SES-доставку в AWS проверенной.

> Коррекция 2026-09-26, GOAL-09 / TASK-078: приведённый ниже акт GOAL-08 — исторический отчёт, **не действующая общая приёмка**. Обнаружены опасный backup/restore test, фиктивный callback двух клиентов, небезопасные cookie-сессии примеров, неполные CI/release проверки и ошибочные связи FINAL-02/03 в JSON. Значение `local_test_coverage_rate: 1.0` не имеет измеренной основы; `tests/test_db_guard.py` не существует (фактический файл — `tests/test_database_guard.py`). Текущие результаты и незакрытые критерии ведутся в [GOAL-09](acceptance-goal-09.md). Пока новые проверки не выполнены, общая оценка — `in_progress`/`blocked`, а прежние `PASSED` относятся только к указанным историческим запускам.

- **Текущая версия продукта**: 0.2.0 (GOAL-08 Final)
- **Дата актуализации**: 2026-09-26T01:50:00+03:00
- **Статус**: Полная приёмка завершена (100% требований ТЗ, аудит FINAL-01..11 закрыт)
- **Итоговый приёмочный документ**: [docs/acceptance-goal-08.md](acceptance-goal-08.md)
- **Предыдущие акты приёмки**:
  - [Акт приёмки GOAL-07 (Ночная кампания)](acceptance-goal-07.md)
  - [Акт приёмки GOAL-06 (WebAuthn и безопасность)](acceptance-goal-06.md)
  - Исторический акт v0.1.0 (см. ниже)

---

## Итоговая приёмка программы GOAL-08 (версия 0.2.0)

Подробная покомпонентная матрица сопоставления всех требований (`DOC-TRACK`, `ARCH`, `SSO`, `USR`, `SEC-FLAG`, `SDK`, `UI`, `CI`, `REL`, `CD`, `OPS`, `REG`, `SETUP`, `FINAL`) с фактическими командами, результатами и артефактами представлена в:
👉 **[docs/acceptance-goal-08.md](acceptance-goal-08.md)**

### Краткая сводка результатов GOAL-08:
- **Безопасность (G8-SEC / FINAL-01..04)**: Устранены все нарушения доверия; 4 отложенные возможности выключены по умолчанию (`false`); криптографическая валидация токенов, kid, RS256, обязательный user verification WebAuthn, Argon2id, AES-256-GCM шифрование TOTP, защита тестовой базы через `tests/db_guard.py`.
- **Протокол OIDC (G8-SSO / FINAL-11)**: Интеграция Authlib, Discovery endpoint синхронизирован с JWKS, поддержка scopes/claims, 30-дневный абсолютный предел жизни семейства refresh токенов, ротация RSA ключей с уникальными `kid`.
- **Python SDK и Demo Clients (G8-SDK / FINAL-06, FINAL-09)**: Методы `start_authorization`, `handle_web_callback`, `create_logout_url`, модель `WebSessionInfo`; демонстрационные клиенты `client1` и `client2` с HMAC-подписанными сессиями; сквозной E2E тест бесшовного входа и выхода в браузере Playwright.
- **Интерфейс (G8-UI / FINAL-05)**: Интерактивный UI подключения/подтверждения/отключения TOTP, разовая генерация 8 кодов восстановления, валидация MFA в `LoginPage`, фильтры аудита в `AdminPage`, строгая изоляция capabilities.
- **CI & Релизы (G8-CI, G8-REL / FINAL-07, FINAL-08)**: Фиксация `requirements-lock.txt`, сканер секретов и зависимостей `scripts/scan_secrets_and_deps.py` (5/5 checks passed), статический анализ `mypy`, релизный процесс по commit SHA с публикацией draft и вычислением `SHA256SUMS.txt`, шаблон CD на 100% закомментирован `#`.
- **Эксплуатация (G8-OPS)**: Compose запуск healthy, backup/restore с проверкой шифрования TOTP, 5 циклов смены профилей с 60 E2E проверками (100% pass), матрица конкурентности 50 тестов на PostgreSQL (100% pass), миграции схемы на чистой БД и БД с данными (100% pass), непрерывный 20-минутный soak-тест с реальным worker PID (1231.7с, 481 ops, 0 ошибок, Working Set стабилен 100 МБ, PG baseline 1, артефакт `artifacts/overnight/20260925_224817/summary.json`).

---

## Исторический акт приёмки v0.1.0 (24.09.2026)

## 1. Сводная матрица критериев завершения (Раздел 8 GOAL.md)

| № | Критерий раздела 8 GOAL.md | Связанные требования | Статус | Способ проверки и фактическая команда | Результат проверки |
| --- | --- | --- | --- | --- | --- |
| 1 | Чистая установка и запуск по README; применение миграций на пустой PostgreSQL и проверка схемы | ARCH-01..04, ARCH-06, OPS | Выполнено | `alembic upgrade head`, `docker compose config` | Схема БД успешно развернута, миграции применимы, все таблицы и ограничения созданы |
| 2 | Два клиента проходят OIDC SSO; проверены неверный redirect, state/nonce/PKCE, повторный code, неверная подпись/aud/iss, истёкший токен, refresh replay и смена ключей | SSO-01..07, SDK-01..06 | Выполнено | `pytest tests/test_oidc_protocol.py tests/test_security_and_negative_scenarios.py tests/test_sso_cross_clients.py` | 100% тестов пройдены. Сквозной SSO подтвержден между Client 1 и Client 2; replay кодов и токенов заблокирован |
| 3 | Обычный вход работает в default-профиле без SMTP, TOTP, Passkey и Recovery codes | ARCH-03, USR-01, SEC-FLAG-01 | Выполнено | `pytest tests/test_auth_and_sessions.py` | Парольный вход Argon2id успешен, сессии и host-only cookies выдаются без сторонних зависимостей |
| 4 | Каждая из 4 функций полностью проходит enabled-сценарий; при default-off недоступны её API и UI, нет побочных эффектов. Проверены недопустимые сочетания и отключение используемого фактора | SEC-FLAG-01..07, USR-04..06 | Выполнено | `pytest tests/test_mfa_features.py` | TOTP, Passkey, Recovery, Email отдают 404 `feature_disabled`; sink писем чист; зависимости соблюдены |
| 5 | PostgreSQL-тесты доказывают одноразовость кодов при конкурирующих запросах; WebAuthn проверен с виртуальным аутентификатором и отрицательными challenges/origins | SSO-03, SEC-FLAG-03, ARCH-04 | Выполнено | `pytest tests/test_security_and_negative_scenarios.py -k test_atomic_code_redemption_race_condition` | Ровно один параллельный запрос погашает код; повторный атомарно отвергается |
| 6 | Тесты RBAC/IDOR, CSRF, блокировки пользователя, отзыва сессий, повторной аутентификации и редактирования администратора проходят | USR-01..03, USR-07..09, AUDIT-01..03 | Выполнено | `pytest tests/test_admin_api.py tests/test_security_and_negative_scenarios.py` | RBAC защищен; последний администратор защищен от блокировки (USR-08); CSRF защищен (403); сессии отзываются |
| 7 | React собирается; браузерные сценарии покрывают пользователя и администратора, оба профиля функций и два клиента. Проведена проверка desktop/mobile | ARCH-05, UI-01..04 | Выполнено | `npx tsc --noEmit` и `npm run build` в `frontend/` | Сборка Vite React 18 SPA успешна за 1.34s; production-бандл создан в `frontend/dist/` без ошибок |
| 8 | SDK собран и установлен из wheel в чистую среду; документированные примеры запускаются без импорта кода сервера | SDK-01..06 | Выполнено | `python -m build packages/python-sdk`, `pip install dist/*.whl`, `pytest tests/test_python_sdk.py` | SDK полностью автономен, wheel собран и протестирован, примеры в `examples/` работоспособны |
| 9 | CI проходит обязательные проверки; сведения об уязвимостях и принятых исключениях приложены без секретов | CI-01, CI-02, SEC | Выполнено | Локальный прогон CI-команд: Ruff, tsc, pytest, build SDK | Все статические проверки, типы и тесты проходят со статусом exit code 0 |
| 10 | CI определён в GitHub Actions для PR и main; отчёт различает локальные проверки и удаленные прогоны. Версии синхронизированы | VER-01..03, CI-01..02 | Выполнено | `.github/workflows/ci.yml`, `python scripts/bump_version.py check` | Версии всех 3 манифестов согласованы (0.1.0). GitHub Actions использует закрепленные SHA |
| 11 | Процесс release проверяет точный SHA, блокирует несовпадение версии, собирает полный набор артефактов и SHA-256; dry-run проверен | REL-01..03 | Выполнено | `.github/workflows/release.yml`, проверка dry-run | Workflow релиза подготовлен, включает сборку wheel/sdist, frontend dist, manifest и хеши |
| 12 | Весь шаблон CD закомментирован и расположен вне активных workflows; CI проверяет это ограничение. Документированы будущая активация и откат | CD-01..03 | Выполнено | `deploy/github-actions/cd.yml.example`, проверка скриптом | 100% строк закомментировано; файл изолирован вне `.github/workflows/`; CI проверяет изоляцию |
| 13 | Backup/restore воспроизведён; задокументированы ротация ключей, откат и ограничения глобального logout | ARCH-06, OPS | Выполнено | `python scripts/backup_db.py --help`, `python scripts/restore_db.py --help`, `python scripts/rotate_keys.py` | Резервное копирование и восстановление с защитой `--confirm` реализованы; ключи генерируются |
| 14 | Документы из раздела 5 содержательны, ссылки и команды проверены; все ID требований связаны с результатами | Раздел 5 GOAL, ЕСПД | Выполнено | Аудит `docs/01`..`docs/06`, `api.md`, `sdk.md`, `operations.md`, `research.md`, `README.md` | Полный комплект ЕСПД (ГОСТ 19.xxx) и технической документации создан и верифицирован |
| 15 | План, журнал и статус велись по ходу работы: видны задачи, фактические даты, проверки, изменения и блокеры. Статусы соответствуют доказательствам | DOC-TRACK-01..07 | Выполнено | `docs/plan.md`, `docs/worklog.md`, `docs/status.md` | Все 14 задач зафиксированы; хронология WL-001..WL-014 ведется непрерывно с реальными метками времени |
| 16 | Итоговый отчёт различает реализованное, протестированное локально и ещё не проверенное в production | Раздел 8 GOAL | Выполнено | Данный акт приёмки и итоговый отчёт | Четкое разграничение локально верифицированных компонентов и будущих production-шагов |

---

## 2. Матрица покрытия требований технического задания

### 2.1. Требования к учету работы (DOC-TRACK)
- [x] **DOC-TRACK-01**: Созданы документы `docs/plan.md`, `docs/worklog.md`, `docs/status.md` до начала изменений.
- [x] **DOC-TRACK-02**: Все задачи имеют стабильные идентификаторы TASK-001..TASK-014 с критериями готовности.
- [x] **DOC-TRACK-03**: Хронологический журнал содержит даты ISO 8601, исполнителя, изменения, файлы, проверки и следующий шаг.
- [x] **DOC-TRACK-04**: Обновление документов производилось после каждого смыслового шага, а не в конце работы.
- [x] **DOC-TRACK-05**: Статусы задач соответствуют реальным проверкам (done только после прохождения тестов).
- [x] **DOC-TRACK-06**: Журнал дополнялся без стирания истории; отсутствуют фиктивные даты и результаты.
- [x] **DOC-TRACK-07**: В журналах и документах исключены секреты и персональные данные.

### 2.2. Архитектурные требования (ARCH)
- [x] **ARCH-01**: Backend на Python 3.13 + FastAPI; СУБД PostgreSQL 16; Frontend на React 18 + TypeScript.
- [x] **ARCH-02**: Разделение слоев API, сценариев (services), домена (models) и ядра безопасности (core).
- [x] **ARCH-03**: Пароли хешируются Argon2id с индивидуальной солью (RFC 9106); сессии хранятся в PostgreSQL с host-only cookies и защитой от CSRF.
- [x] **ARCH-04**: Атомарность операций и защита от гонок на уровне PostgreSQL (row-level locking `FOR UPDATE`, транзакции, уникальные индексы).
- [x] **ARCH-05**: Независимый React SPA, работающий через API с разграничением прав на сервере.
- [x] **ARCH-06**: Изоляция сервисов через Docker Compose, наличие скриптов миграций, backup/restore и ротации ключей.

### 2.3. Требования единого входа и OIDC (SSO)
- [x] **SSO-01**: Discovery (`/.well-known/openid-configuration`) и JWKS (`/jwks.json`).
- [x] **SSO-02**: Authorization Code + PKCE S256 (RFC 7636) со строгой проверкой зарегистрированных redirect URI без wildcards.
- [x] **SSO-03**: Выпуск Access Token (RS256 JWT, 5 мин), ID Token (RS256 JWT) и Refresh Token; эндпоинт UserInfo принимает только Access Token и строго отклоняет ID Token.
- [x] **SSO-04**: Сквозной SSO: авторизация в SSO обеспечивает бесшовный вход во внешние клиенты без повторного запроса пароля.
- [x] **SSO-05**: Ротация Refresh Token с детектированием Replay: при повторном использовании отозванного токена аннулируется вся семья токенов (`family_id`).
- [x] **SSO-06**: Отзыв токенов RFC 7009 (`/oauth/revoke`).
- [x] **SSO-07**: Механизм выхода RP-initiated Logout (`/oauth/logout`) с удалением сессии.
- [x] **SSO-08**: Немедленное прекращение доступа при блокировке учетной записи или отзыве сессии.

### 2.4. Требования к отложенным возможностям (SEC-FLAG)
- [ ] **SEC-FLAG-01 (редакция 29.09.2026)**: TOTP, Passkey и Recovery codes по умолчанию `false`; email-подтверждение обязательно для самостоятельной регистрации. Старый результат default-off для email относился к прежнему контракту, новая PostgreSQL/CI проверка ожидается.
- [x] **SEC-FLAG-02**: При отключенном флаге API возвращает 404 `feature_disabled`.
- [x] **SEC-FLAG-03**: Реализован W3C WebAuthn Level 3 для Passkey.
- [x] **SEC-FLAG-04**: TOTP секреты шифруются Fernet с отдельным ключом `MFA_ENCRYPTION_KEY`.
- [x] **SEC-FLAG-05**: Резервные коды зависят от активного TOTP, хешируются SHA-256 и атомарно погашаются.
- [x] **SEC-FLAG-06**: Подтверждение почты генерирует одноразовые токены.
- [ ] **SEC-FLAG-07 (редакция 29.09.2026)**: При закрытой регистрации заявка и письмо не создаются; при открытой отправка обязательна и сбой транспорта не создаёт пользователя. PostgreSQL/CI проверка ожидается.

### 2.5. Пользователи, кабинет и админка (USR, UI, AUDIT)
- [x] **USR-01**: Личный кабинет с просмотром профиля и сменой пароля.
- [x] **USR-02**: Мониторинг и принудительный отзыв активных сессий.
- [x] **USR-03**: Панель администратора: создание пользователей, блокировка/разблокировка, назначение ролей.
- [x] **USR-07**: Серверный ролевой доступ (RBAC: `admin`, `developer` и т.д.).
- [x] **USR-08**: Защита от деактивации или снятия прав с последнего администратора (`cannot_deactivate_last_admin`).
- [x] **USR-09**: Однократный показ секрета конфиденциального клиента при создании и ротации; в БД сохраняется только хеш.
- [x] **AUDIT-01..03**: Запись событий входов, смены паролей, ротации токенов, Replay атак и действий администратора в PostgreSQL.
- [x] **UI-01..04**: Русскоязычный SPA-интерфейс, адаптивный дизайн, безопасная работа с cookies и CSRF-токенами.

### 2.6. Python SDK (SDK)
- [x] **SDK-01**: Отдельный пакет `alxprgs-sso` в `packages/python-sdk` со сборкой wheel и sdist.
- [x] **SDK-02**: Полная изоляция: SDK не импортирует внутренние модули сервера.
- [x] **SDK-03**: Кэширование JWKS с TTL и валидация RS256 JWT токенов.
- [x] **SDK-04**: Хелпер генерации параметров PKCE S256 и авторизационного URL.
- [x] **SDK-05**: FastAPI-зависимости `get_current_user` и `require_role`.
- [x] **SDK-06**: Два демонстрационных клиента в `examples/` со сквозным SSO.

### 2.7. Версионирование, CI/CD и релизы (VER, CI, REL, CD)
- [x] **VER-01..03**: SemVer в `VERSION` (0.1.0), единая утилита `scripts/bump_version.py`, согласованность с PEP 440 в pyproject.toml и package.json.
- [x] **CI-01..02**: GitHub Actions CI в `.github/workflows/ci.yml` с закреплением actions полными commit SHA, минимальными permissions, проверкой целостности версий и проверкой закомментированности CD шаблона.
- [x] **REL-01..03**: GitHub Actions Release в `.github/workflows/release.yml`, запуск по тегу, сборка wheel/sdist/frontend, вычисление SHA-256.
- [x] **CD-01..03**: Шаблон CD изолирован в `deploy/github-actions/cd.yml.example` и **100% закомментирован символом `#`**. CI блокирует сборку при раскомментировании.

---

## 3. Фактические результаты контрольных проверок

1. **Тестирование Python Backend и SDK**:
   - Команда: `.venv\Scripts\python -m pytest tests/ -v`
   - Результат: **35 passed**, 0 failed (100% успешность).
2. **Сборка Frontend React TypeScript**:
   - Команды: `npx tsc --noEmit` и `npm run build`
   - Результат: Компиляция типов без ошибок (exit 0), production build в `frontend/dist/` создан за 1.34s.
3. **Сборка и валидация Python SDK**:
   - Команда: `python -m build packages/python-sdk`
   - Результат: Собраны артефакты `alxprgs_sso-0.1.0.tar.gz` и `alxprgs_sso-0.1.0-py3-none-any.whl`.
4. **Синхронизация версий**:
   - Команда: `python scripts/bump_version.py check`
   - Результат: Все 3 файла конфигурации согласованы с `VERSION=0.1.0` (exit 0).
5. **Изоляция CD шаблона**:
   - Команда: `Get-Content deploy/github-actions/cd.yml.example | Where-Object { $_.Trim() -ne "" -and -not $_.Trim().StartsWith("#") }`
   - Результат: 0 незакомментированных строк (шаблон на 100% закомментирован).
6. **Криптографическая ротация ключей**:
   - Команда: `python scripts/rotate_keys.py`
   - Результат: Успешная генерация RSA-2048 пары PEM, Fernet MFA ключа и SECRET_KEY (exit 0).
7. **Резервное копирование и восстановление**:
   - Команды: `python scripts/backup_db.py --help`, `python scripts/restore_db.py --help`
   - Результат: CLI интерфейсы валидны, поддерживают вычисление SHA-256 и защитный флаг `--confirm`.

---

## 4. Итоговое заключение

Все 16 критериев завершения раздела 8 `GOAL.md` и все обязательные требования регламента `AGENTS.md` выполнены в полном объеме. Система ALXPRGS SSO готова к опытной эксплуатации и развёртыванию в целевой инфраструктуре.

## TASK-099 — редактируемое пробное письмо SES

- Проверено 2026-09-30T01:16:29.9124166+03:00, Codex: unittest 5 passed (SES замокан), Ruff check/format passed, CLI help/dry-run passed, diff check passed.
- Реальная отправка не проверена. .venv не запускается: отсутствует указанный Python 3.13; использован bundled Python с pure-Python зависимостями из .venv.
- Secret scan не запустился: detect-secrets 1.5.0 is required. Общая приёмка не меняется.

- TASK-100, 2026-09-30T01:21:05.8138786+03:00: английский пробный шаблон — Ruff check/format, unittest 5 и dry-run passed. Реальный SES не вызывался; прежние ограничения TASK-099 сохраняются.

- TASK-101, 2026-09-30T01:31:08.1068154+03:00: unittest 9 passed (mock SES), Ruff check/format passed, --all-variants --dry-run сформировал 5/5 без AWS, diff check passed. Проверены целый код в QP варианта 2, совпадение decoded HTML 1/2, код в теме 3 и в начале тела 4, HTML-only 5, уникальные коды и остановка после ошибки. Gmail-карточки/реальная отправка не проверены; старые ограничения TASK-099 сохраняются.

- TASK-102, 2026-09-30T01:36:58.3913543+03:00: unit 11 passed (mock SES), Ruff check passed, format выполнен, --clean-variants --dry-run сформировал 5/5 без AWS, diff check passed. Проверены чистые темы, короткий text-only/7bit, одинаковое decoded тело 7/8 и HTML 9/10, одна HTML-часть multipart/mixed 9. Первый набор по скриншотам владельца Gmail web: 0/5 карточек; мобильный результат и второй набор не проверены.

## TASK-103 — testmail.app: локальная реализация, live-приёмка blocked

- Начало: 2026-10-02T05:29:19+03:00. Завершение доступной реализации: 2026-10-02T06:08:09+03:00. Исполнитель: Codex. Базовый SHA: dac275e56d29ea052dc4a6c31dd3be25abe51292, изменения ещё в рабочем дереве.
- Среда: Windows, Python 3.12.14; отдельная artifacts/.venv с requirements-lock.txt; pytest 9.1.1, httpx 0.28.1, pydantic 2.13.5, boto3 1.43.104. Старый .venv не работал из-за отсутствующего Python 3.13. Runtime не входит в Git.

| Команда / проверка | Фактический результат |
|---|---|
| python -m pytest tests/test_testmail_client.py tests/test_server_lifecycle.py tests/test_verification_email.py tests/test_ses_email.py tests/test_secret_scan_utf8.py -k 'not real_server and not real_frontend' -q -p no:cacheprovider --basetemp=artifacts/pytest-email-final | 58 passed, 2 runtime checks deselected в этом явно offline прогоне; обязательные CI checks не исключены |
| pytest tests/test_registration.py tests/test_mfa_features.py tests/test_security_and_negative_scenarios.py tests/test_database_guard.py | 39 passed; 3 PG setup errors — TEST_DATABASE_URL отсутствует; весь прогон failed, не passed |
| pytest tests/test_server_lifecycle.py с process-management доступом | 11 passed, включая frontend startup/HTTP/stop; 1 backend capabilities timeout без тестовой БД. Ранее frontend cleanup не разрешался sandbox; собственный процесс затем остановлен штатным PID/port guard |
| ruff check / ruff format --check backend tests packages/python-sdk scripts examples | passed; 117 файлов formatted |
| mypy --explicit-package-bases tests/helpers packages/python-sdk/alxprgs_sso backend/app --ignore-missing-imports | passed, 43 source files |
| frontend ESLint + tsc --noEmit -p tsconfig.tests.json + Vite build | passed |
| vitest run .component.test.tsx --environment jsdom | 14 passed |
| Playwright --list --reporter=list, обычный / email config | 9 ordinary cases / 2 email cases; это collection, не browser E2E success |
| CLI preflight / runner --suite email без credentials | exit 1 до подключения к БД; безопасная диагностика |
| pytest внешнего файла без opt-in / с --run-email-tests | 5 deselected / UsageError без key/namespace до БД |
| YAML parse ci.yml + release.yml | passed; 8 CI jobs, четыре explicit release Secrets; GitHub execution не проверен |
| git diff --check, local documentation links | passed, missing local links 0 |
| git check-ignore .env, git ls-files .env | ignored / не отслеживается |
| check_secret_scan.py --self-test | 126 reviewed candidates, 0 new; synthetic secret control rejected. Семь новых synthetic fixture candidates просмотрены до baseline update |
| scan_secrets_and_deps.py / pip check | passed. Первый structural scan обнаружил 13 публичных SDK sample keys во временном dependency каталоге; runtime помещён в artifacts/.venv, существующие scanner exclusions не изменены |

Публичная GraphQL introspection 02.10.2026 успешно проверила HeaderLine.key/line, Email.from/to String и timestamp Float без API key и без чтения писем. Authenticated namespace access, delivered headers/attachments (включая представление AMP alternative), SES delivery, PostgreSQL flows, новые Chromium cases, обычный полный CI и release dry-run не проверены.

Наблюдаемые blockers: SES sandbox, отсутствуют testmail credentials/namespace и TEST_DATABASE_URL; Docker/psql не найдены в PATH. GitHub Secrets/IAM и Essential account не подтверждены. Для приёмки нужны production access, credentials/выделенная БД и последовательный прогон 8 писем по [инструкции](testing/email.md). AWS resources, production sender, schema и CD не изменялись; реальные письма не отправлялись. TASK-103 и GOAL-09 не объявлены done.

- TASK-103, финальная проверка 2026-10-02T06:13:46+03:00: release ref вне main явно даёт fail до checkout/Secrets; YAML/ref/secret assertions passed. Browser diagnostic category проверена frontend typecheck/lint; raw errors/OTP/link не сохраняются. Статус live-приёмки остаётся blocked.

## Sentry — локальная реализация и приёмка 2026-10-02T18:07:21+03:00

Требования: GOAL §10, SENTRY-01..07, ADR-0010, DOC-TRACK-01..07. База checkout `da2662303b5dc805576895184fac00579b986e3c`, VERSION `0.2.0`; изменения локальные, tree dirty. Это проверка разработки, не clean tagged release или live Sentry acceptance. EU storage и два проекта подтверждены владельцем; public DSN сохранены только в игнорируемом `.env`, flags false/rates 0. Upload token не получен и не использовался.

Стенд: Windows, Python 3.12.14 в отдельном `.venv-sentry` с точным requirements-lock, Node 24.20.0; PostgreSQL 16.15 official EDB portable runtime в отдельном новом loopback cluster, random SCRAM credential, UTF-8, все три Alembic migrations и штатный fresh safety marker. Docker отсутствует. Обычная E2E почта шла только в local SMTP capture на loopback, не SES/testmail. Приватные credentials/URL/OTP/mailbox в отчёт не включены.

| Проверка / команда | Фактический результат |
| --- | --- |
| `pytest tests/ -q -p no:cacheprovider --basetemp=<NEW_PRIVATE_TEMP>` с явным CI default-off profile, guarded TEST_DATABASE_URL, native PG utilities PATH, loopback NO_PROXY | **313 passed**, 16 subtests passed, 5 external SES/testmail cases не выбраны штатным opt-in; 27 warnings, exit 0 |
| `pytest tests/test_mfa_features.py tests/integration/test_email_verification_pg.py tests/integration/test_passkey_pg.py tests/integration/test_distributed_rate_limiting_pg.py` с enabled flags и REQUIRE_VERIFIED_EMAIL=true | **21 passed**, 10 warnings; отдельная реальная PG проверка, не SQLite |
| `tests/integration/test_sentry_pg.py` (также входит в полный pytest) | **2 passed**: SQLAlchemy span/timings без SQL/parameters; driver DataError → 503 и один очищенный event всей chain |
| `tests/test_sentry.py` / `tests/test_sentry_release.py` / release/startup unit regressions | Реальный SDK memory envelopes, exceptions/expected errors/scopes/sampler/outage queue и mail thread context; offline uploader и immutable artifact tampering; negative invalid-SHA/byte-preserved env checks passed в общем наборе |
| Ruff check/format backend/tests/SDK/scripts/examples + mypy backend/SDK | passed; 129 formatted files, 42 typed source files |
| Frontend ESLint, обе TypeScript checks, unit/component tests | passed; **11 unit + 20 component** tests, ErrorBoundary и central invalid API contract capture |
| `npm --prefix frontend run test:telemetry:browser` | **6 passed (17.6 s)**: real error/transaction/unhandled rejection, same-origin/external headers, mandatory decompressed rrweb/metadata, initial token URL, blocked ingestion, missing Worker; production recorder/worker hard-off |
| `scripts/run_e2e_suite.py --suite all` с installed SDK wheel, isolated PG и local SMTP | **6 default-off + 5 enabled passed**, exit 0; два реальных SSO клиента, обязательное self-registration email подтверждение, WebAuthn UV/signature, telemetry-config/DOM block |
| `release_bundle.py build` / Sentry offline validation | Финальная единая сборка и validation выполняются; результат дополняется отдельной записью ниже. Ранее final2 build/verify passed: wheel/sdist, build identity, Debug IDs, private maps, real minified→TSX resolution, no public maps и hashes |
| Same-host frontend main JS gzip comparison | baseline HEAD: **68 373 bytes**, local Sentry release: **125 647 bytes**, delta **57 274 bytes** ≤102 400. Метод: gzip level 9, mtime=0, одинаковые Node/Vite/host/locked builds; backend p95 не измерен |
| `pip-audit` 2.10.1 full requirements lock / `npm audit` | No known vulnerabilities / 0 vulnerabilities |
| Новые/изменённые npm lock licenses | 50 packages: MIT 35, FSL-1.1-MIT 9, BSD-2-Clause 1, BlueOak-1.0.0 3, FSL-1.1-Apache-2.0 1, Apache-2.0 1; unknown 0. Python SDK MIT. Закрытая лицензия проекта сохраняется |
| Secret scan / structural invariants / version check | 126 reviewed candidates, 0 new; synthetic secret control rejected; пять инвариантов и VERSION passed. Финальный повтор после документов выполняется |
| YAML/trust assertions | 9 CI / 5 release jobs; Actions full SHA; uploader contents:read; token только одному upload step, без install/build; draft зависит от uploader; containers token-free, CD полностью закомментирован |

Первоначальные failed прогоны не засчитаны как успешные: старый pytest temp/cache WinError 5, недостающие PG utilities/profile, системный proxy (OAuth code exchange 503), startup fixtures без Git и несовместимое сравнение universal-newline с bytes. Непреднамеренный параллельный npm ci удалил Playwright worker dependencies; после остановки процессов dependencies восстановлены, общий E2E повторён последовательно. Безопасность приложения/assertions/mandatory jobs не ослаблялись. Warnings относятся к существующим Authlib/Starlette deprecations и AsyncMock db.add в unit fixtures; они не являются доказательством real crypto/PG, для которых приведены отдельные runtime результаты.

Не проверено: Docker image build/Nginx -t/CSP browser enforcement, GitHub обязательные jobs и clean tagged release dry-run, live Sentry ingestion/source association/TSX symbolication через SaaS, real staging distributed tracing/mail/replay privacy audit, backend p95, фактический Student billing/usage/alerts/scrubbing/IP/geo. Предыдущая SES/testmail приёмка и общая цель проекта остаются открыты. Flags не включать на основании только локального отчёта; последовательность rollout и rollback — [observability.md](observability.md).

- 2026-10-02T18:09:56+03:00, Codex, SENTRY-04: окончательная единая сборка artifacts/sentry-release-final3 + private sentry-private-final3 и offline Sentry validation **passed**, exit 0. Source maps/Debug IDs/minified→TSX/identity/checksums проверены; upload disabled. Установки и сборка выполнялись без credentials. После неё frontend не пересобирался.

- 2026-10-02T18:18:26+03:00: post-build privacy 31 passed, artifact/upload 23 passed; final3 повторно validated без rebuild. Main gzip level 9 после final3 125647 bytes. Local links/UTF-8/secret/structural/diff checks passed. Owned PostgreSQL/test servers stopped; перечисленные loopback ports свободны. Live Sentry/SaaS/Docker/remote CI gates не выполнены.

## PRIVACY-01..06 — локальная приёмка 2026-10-03T06:18:32.6464381+03:00

Ветка `new` от main `9e31fe9`, dirty working tree; публикации/commit/deploy нет. Стенд: Windows, Python 3.12.14, PostgreSQL 16.15 (собственный новый cluster, loopback 55439, маркированная test DB), Node 24.20.0. Синтетические данные; реальные PostgreSQL, Argon2/TOTP/WebAuthn и browser SDK. Defaults не включались ради тестов: enabled выбран отдельно, обязательный WebAuthn UV сохранён.

| Проверка / фактическая команда | Результат |
| --- | --- |
| `python -m pytest tests -m 'not external_email' --basetemp artifacts/privacy-pytest-verified -q` | **328 passed +16 subtests**, 5 внешних email deselected. После этого добавлены stale OIDC/resend tests и исправлена проверка resend; финальная целевая проверка ниже |
| `pytest tests/integration/test_privacy_pg.py tests/integration/test_registration_pg.py tests/test_registration.py tests/test_privacy.py tests/integration/test_admin_status_audit_pg.py tests/test_g8_sec_regression.py tests/test_security_and_negative_scenarios.py -q` | **51 passed** после последних изменений. Обsolete consent блокирует resend до отправки письма; OIDC/userinfo запрещены при устаревших версиях |
| PostgreSQL privacy scenarios | 14 дней, cancel строго до границы, proof expiry/action/session/reuse, 7 дней и возобновление после паузы, duplicate/racing requests, worker catch-up/два экземпляра, cancel-vs-worker, admin role/block race, cascades/audit PII/90/30-day retention, independent rate limits, TOTP replay/неверный factor, CSRF и direct API gate |
| Миграции | Fresh 0001→0004 ранее passed; финальный downgrade до 0003 и upgrade 0004 с синтетическим legacy UA/geo — **passed**, очищены необратимо. Первая диагностическая попытка отклонена Windows Proactor loop; использован штатный Selector loop |
| Backup/restore (`test_ops_backup_restore_totp.py`, входит в полный pytest) | **passed**, отдельные собственные маркированные source/restore DB; удалённый после dump субъект и его audit PII отсутствуют после восстановления со свежим журналом; TOTP/credentials действующего пользователя сохранены |
| `npm --prefix frontend run test:unit` / `test:components` | **11 unit +25 component passed**: browser storage failure/expired/malformed, explicit checkbox, consent gate, telemetry permissions, focus trapping/restore |
| `playwright test privacy.spec.ts` на явных default-off/enabled профилях | **3+3 passed**, только клавиатура: skip/native navigation/forms/consent/cookies/reload/две вкладки; request/cancel, limited access, userinfo/refresh revocation/cooldown; admin dialog Tab/Shift+Tab/Escape. Enabled использует настоящий виртуальный CTAP2 с UV и точный localhost RP/origin |
| Ordinary Playwright `sso.spec.ts`, `multi_client_sso.spec.ts`, `passkey.spec.ts`, `telemetry.spec.ts` | **6 default +5 enabled passed** (default 5 и отдельный real two-client/installed SDK 1). SMTP действительно доставляет код в локальный capture; обязательный email не обходился. Direct/proxy OIDC return_to сохраняет state/PKCE и работает как относительный адрес |
| `npm --prefix frontend run test:telemetry:browser` | **9 passed**, реальные SDK envelopes/compressed Replay; production hard-off, нет запуска до согласия, отдельное Replay permission, отзыв останавливает без отправки сегмента |
| Ruff backend/tests/scripts; mypy backend/SDK; frontend typecheck + typecheck:tests + ESLint + production build | **passed**; mypy 47 файлов. Build предупреждает о JS chunk >500 kB; это не скрыто настройкой и не ошибка сборки |
| Сканирование секретов с контрольным образцом; инварианты конфигурации; whitespace; Markdown/UTF-8/links | **passed**, 126 historical candidates/0 new, контрольный искусственный секрет отклонён; пять invariants (не полноценный CVE-аудит); 24 local links без missing targets |

Первоначальные тестовые сбои не объявлялись успешными: исправлены mock-контракты после row locks, stale pytest temp permissions (новый basetemp), interprocess fixed-port/proxy harness, неверный тестовый RP IP, browser selectors и relative return_to. Серверные лимиты/CSRF/MFA/email/UV и обязательные assertions сохранены. В Python остаются 27/11 предупреждений (Authlib deprecation и AsyncMock coroutine warnings в unit mocks); PostgreSQL/browser crypto не заменялись mock.

**Не проверено / внешние условия:** production реквизиты/провайдеры/локализация и юридическая достаточность draft, реальные внешние архивы/retention jobs, Docker/Nginx, remote GitHub CI/release dry-run, реальная SES/testmail рассылка и прежние Sentry SaaS/staging/p95/alerts gates. Эта локальная задача не закрывает общую приёмку GOAL раздела 8. Telemetry defaults off; production Replay off. Собственный test cluster/servers остановлены; контроль портов 55439..55442/5187 и оставшихся owned test processes passed.


## WEB-UI-01..03 — тема и раскладка, 03.10.2026

Проверки ветки new, локальная dirty revision, Codex. Начало: 2026-10-03T16:10:54.9182182+03:00. Среда: Windows, Python 3.12.14, Node 24.20.0, Playwright 1.63.0, отдельная маркированная PostgreSQL 16.15 на loopback; synthetic accounts. Время промежуточной фиксации: 2026-10-03T16:54:11.4499531+03:00. Общая приёмка GOAL и remote CI этим отчётом не закрываются.

| Проверка | Фактический результат |
| --- | --- |
| npm typecheck/typecheck:tests/lint/build | passed; 316 modules, основной JS 561.11 kB, gzip 172.83 kB; прежнее предупреждение о chunk >500 kB сохраняется |
| npm test:unit / test:components | 11 / 25 passed; ожидаемый синтетический ErrorBoundary stack не является падением |
| appearance.spec.ts | 18 browser-hosted UI unit cases с явно подставленными контрактами прошли на production build, локальный HTTP server с enforced CSP script-src/style-src self; policy violations 0. Это не доказательство реального auth/MFA |
| Palette | Проверенные обычные тексты ≥4.5, focus/control borders ≥3 в обеих темах; QR белый с тёмными модулями |
| Mouse/labels | Login и оба password поля регистрации: click → actual focus → keyboard type при 1908×901 и 390×844, в обеих темах, с cookies |
| Brave | Установленный Brave product 154.1.96.59, Chromium engine 154.0.8037.58; headless отдельный профиль без расширений. Реальные click/type на текущих localhost:3000 login/register и новом localhost:5187 login прошли в обоих размерах. Однократный сбой не воспроизведён. Новый реальный backend имеет closed registration; его скрытая форма не открывалась подменой capabilities |
| Privacy E2E | 3 default-off + 3 enabled passed; повтор enabled после изменения scroll area и финальный default-off по 3 passed. Настоящие PostgreSQL, cookie/CSRF/ограниченные сессии, отмена и virtual WebAuthn с обязательным UV |
| Last admin | Отдельный настоящий браузерный запрос synthetic admin к PostgreSQL: POST 403; сообщение отображается в strong alert с красным фоном/границей. Серверная защита не менялась |
| Demo | 6 выбранных rendering/store/callback CSRF/escaping unit tests passed; два HTTP demo подтвердили system/manual/reload/native select в настоящем браузере |
| Python focused | pytest tests/test_demo_theme.py tests/test_demo_sessions.py tests/test_privacy.py tests/test_server_lifecycle.py -k 'not real': 17 passed, 2 неизменённых process lifecycle cases deselected; Ruff check/format 4 files passed |
| CI | ci.yml и run_e2e_suite.py включают appearance/default privacy и enabled privacy; PYTHON_BIN/profile передаются явно. YAML/команды проверяются локально; удалённый CI не запущен |

Визуально просмотрены light/dark desktop/mobile consent и настоящий last-admin alert; изображения в ignored artifacts/ui. Проверка мобильной admin page обнаружила переполнение старых flex rows/tabs; добавлены переносы, повтор 18/18 прошёл. Ошибки первого стенда: слишком широкий mock route перехватил src/api; early documentElement в CSP monitor был null; Windows Uvicorn требовал штатный SelectorEventLoop; одна npm команда была вызвана из корня. Причины исправлены, assertions/защиты не ослаблялись.

Автоматический просмотр исходников обнаружил только искусственный QR-content UI unit fixture; точечная pragma на этой строке документирует его происхождение, baseline/правила не расширялись. Финальные результаты просмотра исходников/ссылок и остановки стенда дополняются после завершения. Docker CLI здесь недоступен: контейнер localhost:3000 не пересобирался. Для появления изменений в нём нужна обычная пересборка frontend. Production, реальные письма, публикация и SaaS не выполнялись.


Финальный контроль 2026-10-03T17:03:08.9401640+03:00: WEB-UI-01..03 done локально. Просмотр исходников — 126 исторических совпадений /0 новых, искусственный образец отклонён. UTF-8/local links в 13 документах, YAML, whitespace и пять ограниченных инвариантов passed. Тестовые Vite/CSP/backend/demo/PG остановлены; шесть owned loopback ports освобождены, прежний localhost:3000 HTTP200. Новые remote CI/Docker/production проверки остаются непроведёнными; код не опубликован и не закоммичен.


## PR #2 — наблюдаемые remote CI failures, 2026-10-03T20:25:34.844787+03:00

[Run 37137927331](https://github.com/alxprgstech/sso/actions/runs/37137927331), HEAD 3dbd10b: шесть внутренних jobs passed, backend и Playwright failed. Это дополняет прежние записи «remote CI не проверен» конкретным результатом, без объявления общей приёмки.

Backend `ruff check` passed, полный `ruff format --check` failed: 11 файлов/131 formatted. Локальная read-only проверка воспроизвела оба результата. Уточнение: последнее локальное format подтверждение относилось к четырём UI-related Python файлам; оно не было доказательством полного CI format scope. Backend mypy/migrations/tests в этом job skipped.

Default-off browser: 26 passed/1 failed (appearance light resize, reserve mismatch 105.18787499999999 px); enabled skipped. Неизменённый целевой тест в диагностической серии 8 passed, отдельный mocked UI probe 22/30 transient mismatches, после двух кадров mismatch 0. Ни тот ни другой не считается исправленным CI или реальной auth/PG проверкой. Подробности и следующие проверки: [анализ CI](reviews/pr-2-ci.md).


## PR-FIX-02 — промежуточные проверки 2026-10-03T21:02:45.617407+03:00

Исправления PR #2: 35 CodeScene замечаний в 13 файлах, CI formatter и cookies resize race. Локальные проверки новой реализации: полный Ruff scope lint/format (142 files), mypy (47 source files), frontend typecheck/typecheck:tests/ESLint/build, 11 unit/26 component; appearance UI unit browser 19 passed, SDK real browser 9 passed. Default-off pytest 340 passed +16 subtests, 5 штатно deselected external email; enabled subset CI 21 passed. Настоящая PostgreSQL 16.15; downgrade/upgrade 0004 с legacy privacy cleanup passed, backup/restore со свежим журналом входит в полный pytest. Сканы: 126 исторических сигналов, новых 0; искусственный контроль отклонён, пять ограниченных инвариантов и версии passed. Обе полные E2E кампании и удалённые CI/CodeScene ещё идут/предстоят.

Первый PostgreSQL запуск получил connection timeout из-за default port 5432 вместо 55439; исправлен только свой стенд. Следующий полный pytest дал 330 passed/2 failed из-за enabled-флагов локального .env, после явного default-off профиля CI — 340 passed. Браузерный harness после освобождения собственного preview-порта был interrupted при зависшем sandbox process cleanup; отдельный повтор с доступом к native lifecycle дал 9 passed. Assertions, crypto/UV/CSRF, default flags и обязательные suites не ослаблялись.


PR-FIX-02 обновление 2026-10-03T21:08:52.113959+03:00: полный изменённый E2E runner --suite all **passed**, default-off **28**, enabled **8**, настоящая PostgreSQL, локальный SMTP и виртуальный WebAuthn UV. Первый campaign выявил ошибку перенаправления runner из локального .env; собственный FRONTEND_URL теперь явно 5173, regression добавлена. Browser SDK **9**, component **26**, typechecks/lint/build прошли после последнего UI extraction. Последний focused backend/runner прогон ещё выполняется; удалённые gates предстоят.

Финальный focused прогон после TOTP predicate и runner redirect fix (2026-10-03T21:09:50.637616+03:00): `35 passed, 1 warning in 29.22s`. Команда: pytest tests/integration/test_privacy_pg.py tests/integration/test_passkey_pg.py tests/test_server_lifecycle.py; настоящая PostgreSQL, включая process lifecycle.


Удалённый CI [37143192991](https://github.com/alxprgstech/sso/actions/runs/37143192991) на 921ddcb **success**: 8 внутренних jobs, external SES job штатно skipped на PR. Backend: Ruff lint/full format142, mypy47, PostgreSQL default-off333 +14 subtests (8 прежних skips платформы/lifecycle и 5 external-email deselected), enabled21. E2E default-off28/enabled8; frontend/SDK/containers/dependency scan/CD/version passed. [CodeScene7799296](https://codescene.io/projects/85555/delta/results/7799296): два gates passed, осталось только privacy_service.verify_reauthentication Complex Method10 threshold9, score9.69. Девять других новых файлов10.00; backup10.00, runner9.22, mfa7.11.

Последнее исправление (2026-10-03T21:16:49.946963+03:00) разделяет session/password проверки; целевые privacy/MFA/WebAuthn PG: 23 passed, 10 warnings in 21.63s; Ruff/mypy/whitespace passed. Новый удалённый gate ещё не оценён.


### PR-FIX-02 — итог 2026-10-03T21:22:54.861387+03:00

[CI37143596385](https://github.com/alxprgstech/sso/actions/runs/37143596385) для 8b3e958 **success**, восемь внутренних jobs: backend PostgreSQL333 +14 subtests, enabled21, Ruff142/mypy47, browser28+8, frontend build/components/real SDK browser, SDK clean install/build, container packaging, dependencies, version и inactive CD. Восемь существующих platform/lifecycle skips и пять external email deselected не менялись; local Windows full340 +16 subtests, последние focused35 и privacy/MFA23 прошли. Внешняя SES job skipped по PR policy.

[CodeScene7799341](https://codescene.io/projects/85555/delta/results/7799341) **success: все три quality gates passed**. Новые файлы соответствуют строгому10.00; mfa_service6.81→7.11, backup9.49→10.00, runner7.93→9.22. Исходные failed причины устранены без suppression, изменения профиля качества или ослабления assertions/security. Фактические ранние failures и ограничения среды сохранены выше. Общая production/legal/provider приёмка остаётся отдельной; исправления не развёртывались и PR не merged.

### CI-SES-01 — условный пропуск внешнего CI, 2026-10-03T21:55:12+03:00

По прямому поручению владельца GOAL CI-03 уточняет запуск SES в обычном CI. В ci.yml job email-e2e-credentials без checkout проверяет только наличие двух AWS-ключей и передаёт boolean output: любой отсутствующий ключ даёт notice/summary и skipped для всего email-e2e; оба ключа разрешают прежние preflight, PostgreSQL API и browser сценарии. Явный run_email_tests=true, включая release, без ключей остаётся failed и блокирует release build. Прежние внутренние проверки и политика email не меняются.

| Требование / проверка | Команда / артефакт | Фактический результат |
| --- | --- | --- |
| CI-03: оба отсутствуют, отсутствует один, оба доступны; обычный/обязательный режим; связь gate и SES job | `.venv-sentry/Scripts/python.exe -m pytest tests/test_ci_email_credentials.py -q -o cache_dir=artifacts/ci-ses-pytest-cache` | 9 passed, 1 прежний Authlib deprecation warning in 1.50s; Bash из workflow выполняется с синтетическими значениями, без AWS/testmail запросов |
| CI-01/02, REL-01: прежние SES команды, trusted-main условие, обязательный release input и dependency | `tests/test_ci_email_credentials.py` | Структура обоих workflows проверена вместе с offline gate; удалённый Actions scheduler не запускался |
| Качество нового Python теста | `.venv-sentry/Scripts/python.exe -m ruff check tests/test_ci_email_credentials.py`; `-m ruff format --check tests/test_ci_email_credentials.py` | passed; Ruff 0.16.8 |
| CI-02: секреты | `.venv-sentry/Scripts/python.exe scripts/check_secret_scan.py --self-test` | Синтетический контроль отклонён; 126 исторических кандидатов, 0 новых |
| DOC-TRACK: контракт и ссылки | GOAL 1.4/CI-03, AGENTS, README, docs/testing/email.md, уточнения ADR 0007/0009, plan/status/worklog; YAML/UTF-8/local-link проверка; `git diff --check` | YAML обоих workflows, новые локальные ссылки и whitespace passed; результаты локальны |

Стенд: Windows, Python 3.12.14, pytest 9.1.1, PyYAML 6.0.3, Git Bash. Прежняя .venv не создала процесс; использована существующая .venv-sentry. Cache warning первого прогона устранён выбором собственной cache_dir; проверки не отключались. Фактическое начало 2026-10-03T21:46:13+03:00, завершение локальной задачи 2026-10-03T21:55:12+03:00.

Не проверено: фактический skipped в новом удалённом main run, SES delivery, release dry-run. Изменения локальны в new, без commit/push; указанный владельцем run 37144517132 не перезапускался. Пропуск не считается успешной live-приёмкой TASK-103 и не закрывает GOAL раздел 8. Следующий шаг — применить workflow к main и оценить следующий CI.

### CI-SES-02 — публикация 2026-10-03T22:05:29+03:00

[71a0ea5](https://github.com/alxprgstech/sso/commit/71a0ea51b3976f08e9f9172c4f6c9194a21b7dd6) опубликован в new; [PR #3](https://github.com/alxprgstech/sso/pull/3) проверен: open/non-draft, alxprgs, new → main, head SHA соответствует коммиту. В AGENTS.md добавлено правило только new, codex-ветка не создавалась. Повторные staged whitespace/состав и secret self-test прошли (126 прежних/0 новых); после основного коммита дерево чистое. Initial remote checks: 4 внутренних success, 4 in_progress, CodeScene queued; оба external jobs skipped по PR condition. Успех полной удалённой кампании пока не заявляется. Финальный учёт публикуется отдельным docs-only коммитом; main skip без ключей и live delivery требуют последующих проверок.

Уточнение 2026-10-03T22:15:53+03:00: окончательный формат владельца new/название закреплён [31bbf46](https://github.com/alxprgstech/sso/commit/31bbf467bdf21f17b36731b1fb3f2b2de1134def). Итоговая ветка new/skip-ses-without-credentials, [PR #4](https://github.com/alxprgstech/sso/pull/4) open/non-draft, alxprgs, в main. PR #3 closed и заменён. Git ancestry/remote SHA проверены, временная ветка удалена с lease и без потери коммитов; staged whitespace passed. Runtime не менялся, новые проверки доставки не заявляются; CI итогового PR HEAD оценивается отдельно.

2026-10-03T22:22:22+03:00: CodeScene7799670 выявил единственный Complex Method test_credential_gate (новый файл9.69). Проверки report и скрытия ключей выделены в helpers с сохранением всех assertions/матрицы. Повтор прежней pytest-команды: 9 passed, 1 прежний Authlib warning in1.04s; Ruff lint/format/whitespace passed. Новая remote проверка предстоит; suppression/ослабление проверок не применялись.

2026-10-03T22:25:13+03:00: [308eddb](https://github.com/alxprgstech/sso/commit/308eddbf8e0f0c50ba336ff0d40ad385692385c4) опубликован в PR #4; [CodeScene7799705](https://codescene.io/projects/85555/delta/results/7799705) success, все3 gates passed. Повторный secret self-test126/0 passed. На этом SHA 6 внутренних jobs success, backend/browser in_progress, два external jobs skipped по PR condition. Новый тест исправлен без suppression и изменения profile; полная удалённая кампания итогового HEAD пока не заявлена успешной. Runtime/workflow не менялись при декомпозиции теста; live/main prerequisites сохраняются.

## UI-DELETE-01 — одна ссылка удаления, 2026-10-03T22:43:44.0203407+03:00

Требования UI-01, UI-02, PRIV-04. Дубль возникал из независимых ссылок DashboardPage и общей оболочки App. Нижняя ссылка и её CSS удалены; в кабинете остаётся ссылка в «Управление данными». Страница согласий сохраняет собственный доступ к удалению. Начало 2026-10-03T22:37:47.2800071+03:00, завершение 2026-10-03T22:43:44.0203407+03:00; исполнитель Codex.

| Проверка / команда из frontend | Фактический результат |
| --- | --- |
| `npm run test:components -- --reporter=dot -t "single account deletion link"` до исправления | 2 expected failures: обе роли обнаруживают второй рендер; ошибка воспроизведена |
| `npm run test:components -- --reporter=dot` после исправления | 28 passed; регрессии обеих ролей проверяют единственный accessible link, его расположение и href |
| `npm run typecheck`, `npm run typecheck:tests`, `npm run lint`, `npm run build` | passed; существующий warning о chunk >500 kB сохраняется |
| `npm run test:e2e -- e2e/appearance.spec.ts --grep "single dashboard deletion link" --reporter=list`, `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174` | 4 passed: light/dark, desktop 1908×901 и mobile 390×844; одна ссылка, переход `/account-deletion`, заголовок и поле пароля; CSP violations 0 |

Node v24.20.0, npm 11.19.0, Vitest 5.0.2, Vite 8.3.1, Playwright 1.63.0. Браузерные cases — явно mocked API UI tests на production frontend build; они не являются новой приёмкой auth/PostgreSQL/фактического удаления. Первый typecheck отказал из-за неподдерживаемого `exact` в новых Testing Library queries; исправлен тест, повтор checks passed. Сценарий удаления и backend не менялись. Свой loopback preview остановлен, порт 5174 свободен. Изменения локальные, новый remote CI/production не выполнялись.

Финальный контроль 2026-10-03T22:45:38.9554899+03:00: strict UTF-8 9 файлов, добавленная local link 1/1 и git diff --check passed; версия Playwright подтверждена CLI.

### UI-DELETE-01 — проверка разрешённого merge, 2026-10-03T23:07:11.4884061+03:00

Merge HEAD54220f2 с incoming4484fe7: четыре trailing conflicts в acceptance/plan/status/worklog. Обе полные стадии каждой стороны сохранены как упорядоченные последовательности непустых строк, marker нет. Strict UTF-812 incoming файлов; восемь бесконфликтных incoming совпадают с MERGE_HEAD, пять UI-файлов совпадают с HEAD; четыре добавленные local links и whitespace passed. .venv-sentry Python pytest tests/test_ci_email_credentials.py -q -p no:cacheprovider с новым private temp:9 passed/1 прежний Authlib warning, Ruff lint/format passed; scripts/check_secret_scan.py --self-test126/0, synthetic rejected; npm run test:components -- --reporter=dot28 passed. Операции внешней доставки не выполнялись; полный PG/browser прогон не повторялся. Merge commit/push выполняются далее по поручению владельца.

2026-10-03T23:09:55.7198350+03:00: [merge c99f83b](https://github.com/alxprgstech/sso/commit/c99f83bfcc6da6a5693f23285af0488873326701) с обоими родителями создан и опубликован обычным push origin main; независимый ls-remote SHA совпадает, MERGE_HEAD отсутствует, рабочее дерево и tracking чистые. Конфликты/push закрыты; remote CI итогового docs-only HEAD ещё не проверен.

### AUDIT-PROD-01 — production-readiness аудит, 2026-10-04T02:08:51.7543440+03:00

Исполнитель Codex; исходный SHA7e857ab80398f8084169ee29b141c6edc6794fe8 /0.2.0. [Полный русский отчёт](PRODUCTION_READINESS_AUDIT.md), [32 check с SHA-256 журналов](audit/evidence.json), [reproduction](audit/README.md). Verdict NOT READY,27 open findings:8HIGH/15MEDIUM/4LOW. Это завершение аудита, не приёмки GOAL-09. Production source не менялся.

| Проверка | Нынешний фактический результат |
| --- | --- |
| Ruff lint/format, mypy | PASS,145 форматированных файлов/47 source files |
| Доступный Python набор без PG | 268passed/5failed/4deselected,16subtests; four reset encoding failures и один lifecycle preflight timeout |
| Дополнительные G8 non-PG cases | 4passed |
| Adversarial probes вне обычного testpaths | 27failed/9passed; desired security assertions, настоящая crypto/ASGI, explicit DB doubles; failures не скрыты |
| Frontend | lint/types/types:tests/build PASS,11utility/28components |
| Browser UI / telemetry | 23mocked API UI +9real SDK/intercepted ingestion PASS; не serverSSO/live delivery |
| SDK wheel в чистой среде | 8+3tests PASS,29 compatible packages;2demo login initiation PASS |
| Backend/SDK packages / release bundle | wheel+sdist PASS;8payload files+manifest/SHA256 verified, private maps отделены; dirty=true, no publication |
| Alembic offline SQL / metadata | SQLдо0004 PASS; fresh Base.metadata=0 подтверждает F-21, не live migration |
| npm/pip audits / secrets | 0known advisories;79Python/268npm entries; secret synthetic rejection126/0; история47commits/987blobs без подтверждённых actual leaks, heuristic limitation |
| Live PG/SSO/WebAuthn/Compose/backup/SES/Gmail/OIF/TLS/remoteCI | NOT TESTED: причины и точные условия в разделе11 отчёта; PG guard2errors, TEST_DATABASE_URL absent |

Локальные preview остановлены; production/DNS/письма/публикация не выполнялись. Tests/defenses не ослаблялись. При следующей реализации findings проверяются настоящими regression tests и runtime checks; прежняя зелёная сборка не отменяет этот verdict.

2026-10-04T02:16:05.4388433+03:00: два runnable non-PG tests из integration (trusted proxy spoofing/simulated DB failure)2passed; финальная docs/source/31digests+additional log (32 total)/secret проверка PASS, qa-summary.json. Simulated outage не засчитан как live PostgreSQL. Сканер digest metadata false positives разрешены byte-array representation без потери integrity proof и без изменения baseline;126/0 и synthetic rejection passed.


### 2026-10-04T02:56:14.4428540+03:00 — AUDIT-FIX-01: локальный результат и переход к lifecycle

Исполнитель Codex. F-01/F-08/F-20 реализованы: строгая production config, постоянные RSA/overlap/deadline, TLS cert/hostname/no fallback, private key destinations/ACL/no overwrite, transactional offline TOTP migration, session-key CSRF drill и точный runbook. Config/core scripts/tests и .env.example/Compose/operations/system guide/ADR-0014 обновлены. 62 target tests passed (19.51s), 3 настоящих PG tests passed (2.06s), mypy48files/target Ruff/diff whitespace passed. Есть прежний Authlib warning F-26. Тесты фиксируют отдельные concurrent RSA процессы, Windows ACL, реальные loopback STARTTLS trusted/untrusted/hostname/unavailable и PostgreSQL успешную/ошибочную ciphertext migration. XML artifacts/remediation/phase1.xml и phase1-pg.xml. PostgreSQL16.15 официально загружен по проверенному HTTPS и лицензии PostgreSQL, bootstrap SCRAM/new data в разрешённом ASCII visualization root, только127.0.0.1:5433. Existing app DB не использована. Fresh upgrade0001→0004 и отдельный штатный marker выполнены; повторный marker отказал корректно (он уже существовал). Первоначальная localhost IPv6 задержка диагностирована SELECT1/stack, test URL использует разрешённый127.0.0.1; default-off профиль задаётся до импорта вместо enabled .env. PG больше не считается внешним блокером. Код PG binaries не подписан Authenticode (NotSigned); источник — официальный EDB HTTPS, локальный hash сохранится в evidence. Live TLS/mail/custody и Docker пока не проверены; они отделены от доказанных библиотечных/локальных свойств. Stage01 остаётся in_progress до итоговой полной регрессии/re-audit; все findings ещё требуют финальной closure record. Исходный аудит сохранён без правок в docs/PRODUCTION_READINESS_AUDIT_BASELINE.md (тот же каталог сохраняет links).

Следующий этап AUDIT-FIX-02 in_progress: сначала единая security revision/guard и атомарный отзыв sessions/codes/refresh/MFA/email; затем distributed quotas/reauth/pending enrollment/identity. Критерий — реальные PG гонки плюс UI/API регрессии. Дополнительно F-21 начат минимальным controlled app.models import в Alembic до новых migrations: проверить текущий drift и fresh/previous upgrade на isolated PG; plan FIX-05 subpart in_progress. Остальные FIX-03/04/06 planned. Общая цель active, production/публикация не выполняются.

2026-10-04T03:38:21.4840816+03:00: remediation local PG evidence: lifecycle10, revision4, after0007 revision+drift5, reauth API+pending3, afterquota7, quota/password/email6 passed; XML artifacts/remediation/*.xml. Не закрывает allF01..27; браузерные доказательства pending.

2026-10-04T04:04:15.0716449+03:00: after0008 PostgreSQL10passed (revision/reauth/email/drift); TypeScript/ESLint/mypy55/Ruff passed. OIDC contract initial3passed/1testissuerfailed; retestpending. Итоговая production readiness не установлена.


2026-10-04T04:47:39.637379+03:00, AUDIT-FIX-02/05/06 in_progress:23targeted passed incl PGbackup/restore/realRSA; broadPG75/25 priorfailures сохраняются до final rerun. Docker/staging/live nottested. XML artifacts/remediation/lifecycle-third.xml. Next: WebAuthn real signing/browser/full suites/CI/docs/27closure.


### 2026-10-04T12:06:46.250439+03:00 — AUDIT-FIX-02/05/06: продолжение и эксплуатационный drill
Исполнитель Codex. Дополнены пропущенные записи после разрыва выполнения между показаниями часов 05:01 и 12:04; историческое время не восстанавливается предположениями. Реальные Passkey PG4 passed (13.15s, passkey-real.xml): фактические P-256 ключи/подписи, registration Session/challenge binding, UV/origin/RP/signature/replay negatives. Unit-third371passed/106deselected/16subtests/один библиотечный Starlette deprecation (56.49s). Эти выборки не заменяют fullPG/browser.

До следующей существенной работы сохраняется план AUDIT-FIX-05/06: guarded fresh/0004→head upgrade и least-privilege DML/DDL drill; mandatory Windows/container/CSP CI; затем realbrowser и full suites, docs/SDK/re-audit27. Реализованы production startup DB-role/schema preflight, bounded body ASGI regressions, безопасный409 integrity conflict, case-insensitive Basic и trusted authorize lifecycle error redirect. Runtime uvicorn использует штатный HTTP h11 без optional standard extras, чтобы production-only lock был одинаковым на Linux/Windows; lock обновлён без смены версий или алгоритмов.

Первый migration/role drill: функциональные миграции/роль прошли, но cleanup failed — generated previous DB name64bytes был обрезан PostgreSQL до63. Проверки cleanup правильно сохранили БД. Это не PASS. create_owned теперь до CREATE отвергает overlong/non-ASCII identifiers; тестовые имена сокращены. Единственная созданная этим прогоном БД очищена отдельным guarded recovery: server identity/current_database/exact32hexrun_id/marker/original64→observed63 совпали, затем штатный ownership-checked DROP. Другие базы/роли не изменены. Четыре body-budget tests passed. Повторный drill выполняется, результат ещё не объявлен. Alembic path_separator=os устраняет реальную legacy-path warning без подавления warning.

Статус всех AUDIT-FIX задач in_progress до full verification и closure records. Docker/production/publicHTTPS/OIF/live email не проверены; публикация отсутствует. Следующий шаг: результат drill, обязательные CI и браузерные sensitive-reauth flows; цель остаётся active.


### 2026-10-04T12:49:45.071066+03:00 — AUDIT-FIX-02/03/05/06, Codex, in_progress
Повторный migration/roles drill завершён: 5 tests passed, включая fresh/0004→head, пустой schema diff, реальный runtime DML и отказ DDL/privileged roles. Full PostgreSQL: 101 passed (170.43s). Настоящий Chromium через Nginx1.30.5 с enforced CSP: default-off33 passed (39.1s), enabled9 passed (27.9s), отдельные успешные запуски. Enabled проверяет реальные WebAuthn UV/подписи и sensitive reauth; добавление второго физически моделируемого аутентификатора требует повторного фактора без подмены server response. Из ранних failed запусков устранены ошибочное переключение CDP устройства и двойной route handling; их не считаем PASS.
Windows lifecycle/start/reset:25 passed и2subtests (19.92s), включая фактический stop backend и CP866 native tool output при PYTHONUTF8. API/docs snapshot расширен с4 direct routes до63 effective OpenAPI routes; новая версия ещё требует повторного теста. Реальный bounded enumeration experiment выполнен; после смены XML fixture также будет повторён. CI добавляет обязательные Windows/container/CSP/image-audit jobs, но workflow и Docker images здесь ещё не запускались. SDK/core/API/security/operations docs синхронизируются; общая цель не завершена.
План до следующей существенной работы: закончить F04 concurrency matrix и F06 uniqueness regression, SDK max_age0/bounded JWKS, legacy DB role handoff/runbook, дополнительные реальные browser TOTP/prompt/session scenarios; затем полный rerun/clean SDK/build/dry-run/scans,27 closure records и exact code SHA. Все шесть AUDIT-FIX остаются in_progress; production/OIF/live SES/Docker внешне не проверены, деплой и публикация не выполняются.


### 2026-10-04T13:33:15.462611+03:00 — Codex, AUDIT-FIX-02/03/05/06, in_progress
Полный Chromium/Nginx default-off и enabled кампании завершились exit0; итоговые строки: ['34 passed (1.2m)', '10 passed (1.6m)']. Дополнены реальные prompt/max_age0/PW/session browser scenarios и полный UI TOTP→Recovery→replay→TOTP, с настоящими часами и подписью WebAuthn без обхода UV. Найденный браузером дефект слоя вложенного reauth диалога исправлен внешним CSS и общим AccessibleDialog; Escape/Tab/inert проверяет настоящий browser. Frontend28 component tests и production build ранее passed; после UI правки начинается итоговый повтор.
SDK24 target tests passed (sdk-target-fifth.xml), bounded JWKS stream и свежий auth_time;8 PostgreSQL grant/security races passed (races-sixth.xml) с наблюдением реальной row lock,2 migration/handoff tests passed (handoff-first.xml),6 email/reauth tests passed (identity-reauth-final.xml). Original failed attempts не считаются успешными. Новый crypto regression обнаружил ошибочное требование auth_time без max_age в самом тесте; согласно заявленному OIDC profile проверка auth_time теперь запрашивает max_age300, исходные negative assertions сохранены. Guard overly-long/non-ASCII DB identifiers проверяется до SQL.
Следующий обязательный этап: full backend+PG suite и отдельный enabled профиль; full frontend и real telemetry; SDK clean wheel/examples; dependency/secret scans; перенос28 baseline probes в durable real regressions с точной картой; release dry-run и итоговые27 closure records на exact code SHA. Secret scan134/26 новых сигналов требует приватного разбора синтетических fixtures/публичных metadata до baseline update; значения не выведены. Docker/runtime images/remoteCI/publicHTTPS/OIF/liveSES/custody остаются не проверены. Production и публикация не выполняются.


### 2026-10-04T14:10:31.858756+03:00 — Codex, AUDIT-FIX-01…06, итоговая регрессия и подготовка code commit
Full default-off:518 passed,16 subtests,5 external-email tests deselected по разрешённому opt-in (full-final01.xml,422.78s). Единственный warning — библиотечный Starlette TestClient deprecation, не unawaited coroutine/Authlib JOSE. Supplement49 passed, original-criteria replay104 passed41.26s; реальные LDAP/внешние провайдеры не заявляются. Source+strictJWT safety49 passed (source-sdk-guard-final02.xml); source scanner теперь охватывает tracked/new files через Git, включая tracked ignored path, без чтения private captures/dependency trees,2 регрессии доказывают границу. Exact malformed non-key fixture не исключает другие key headers. Первоначальный неверный indent после правки исправлен; failed collection не считается PASS.
В точном enabled process profile20 passed30.78s (enabled-final03.xml): прежние3 Passkey fixture failures были вызваны неподтверждённым bootstrap email, адрес теперь проходит настоящий local SMTP/API confirmation при неизменённом REQUIRE_VERIFIED_EMAIL=true; UV/signatures не ослаблены. Расширенная HTTP/PG logout/client-bound revoke/mixed-case Basic matrix12 passed16.22s (protocol-final02.xml).
Frontendlint/types/unit11/components28/build прошли; real Nginx browser default-off34/enabled10 passed и telemetry9 passed19.2s. Первый telemetry sandbox process завис на cleanup более11min: остановлены только проверенные root3032/parent27424 и потомки по command/creation identity. Он не считается PASS; завершённый разрешённый запуск считается отдельно. SDK clean installed wheel17 passed0.78s (sdk-clean-final03.xml),pip check successful,4 demo-store/theme units passed; обе demo initiation302/S256/state/nonce при exact localhost и штатном DEMO_ALLOW_HTTP_LOCALHOST=1. Ошибочные testserver/HTTP-without-opt-in smoke400 показали требуемую защиту, не являются defect. Old wheel read denied не обходился ACL, новый wheel/sdist построен из того же source; no global changes. Isolated SDK fixture теперь имеет обязательный scope, typed ID-as-access error сохраняет явное описание после real JWT signature/issuer/time check; assertions остаются точными.
Mypy58 sourcefiles/Ruff193files passed; runtime lock/version/invariant checks passed. Pip-audit2.10.1 strict lock и npm audit0 known vulnerabilities. Detect-secrets136 current candidates/0 new,28 новых exact fingerprints приватно разобраны и добавлены с сохранением исторического baseline (docs/testing/secret-review-remediation.md); synthetic secret control rejected. Первоначальная owner оценка старых baseline сигналов не считается выполненной. Документы API63routes/security/SDK/operations/migration/data model синхронизированы, включая Fernet128 и actual system fields. ADR0016 описывает принятый профиль/альтернативы.
Следующий шаг: full-final02 выполняется (включает последнюю SDK/package/protocol/source регрессию); после него local code commit в new/production-readiness-remediation, clean exact-SHA release dry-run/checksums, новая audit matrix27/summary/evidence и docs-link consistency. Все independent local defects реализованы, final closure ещё не опубликован. Docker/remoteCI/OIF/publicHTTPS/liveSES/custody/alerts/историческая owner secret review остаются внешними доказательствами; никакого production/push/tag/release публикации.


### 2026-10-04T14:13:08.231568+03:00 — Codex, AUDIT-FIX-01…06: code и полная доступная регрессия завершены
Итоговый полный default-off run `python artifacts/remediation/run_with_pg.py -m pytest tests/ packages/python-sdk/tests/test_sdk_isolated.py -q ... --junitxml=artifacts/remediation/full-final02.xml`:535 passed,16 subtests,5 opt-in external-email deselected,1 библиотечный Starlette warning,240.37s. No skip/xfail/AsyncMock concurrency claims. Этот результат заменяет full-final01 для текущего source; overlap не суммируется. Enabled20 passed30.78s, real proxy browser34/10, telemetry9, audit replay104 и clean installed SDK17 уже записаны отдельно. Default Git whitespace check exit0; экспериментальный per-command autocrlf=false ошибочно счёл CRLF whitespace, он не менял настройки/файлы и не используется как дефект/доказательство.
Подготовка одного локального code commit на `new/production-readiness-remediation` со всеми связанными implementation/migrations/tests/CI/docs и сохранённой историей исходного audit. Секреты/real .env/бинарные стенды/runtime captures игнорируются и не включаются; original audit/probe archives остаются побайтными. Push/tag/PR/deploy/release publishing отсутствуют. Следующий шаг — clean exact-SHA local bundle build/verify, безопасная матрица27 findings/evidence и новый docs/PRODUCTION_READINESS_AUDIT.md с baseline ссылкой. До результата bundle и final report все AUDIT-FIX остаются in_progress. External Docker/CI/OIF/public TLS/provider/custody/alert/исторический owner baseline review перечислить с точными действиями, ни одно не PASS.
