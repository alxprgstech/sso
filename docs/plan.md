# План ALXPRGS SSO

Обновлено 20.10.2026. Сокращён по поручению владельца (DOC-CLEANUP-02). Текущие требования: [ТЗ](01-technical-specification.md), AGENTS.md. Хронология сохраняется в [worklog](worklog.md); [исходный план](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/plan.md) хранит подробные критерии, зависимости, начало/завершение и промежуточные результаты всех прежних ID. Старые задачи не отменены очисткой; исторический blocked/planned не превращён автоматически в done.

## Текущие задачи

| ID | Приоритет | Зависимости | Статус | Критерий и следующий шаг |
| --- | --- | --- | --- | --- |
| DOC-VERSION-LOCK-01 | P2 | DOC-REFRESH-01, DOC-DEF-01 | planned | Bump/check учитывают root package-lock version и packages[""].version; regression в отдельной копии без изменения dependency resolution. Начало реализации не назначено. |
| AUDIT-FIX-03 | P1 | Локальное OIDC remediation, внешний стенд | blocked | Выполнить применимую OIF matrix на утверждённом публичном HTTPS issuer с отдельными клиентами; локальный retest не заменяет внешний результат. |
| AUDIT-FIX-05 | P1 | Локальное ops remediation, утверждённая инфраструктура | blocked | Подтвердить public TLS/DNS/IAM/secret storage, внешние backup/storage ACL и alerts. Локальные Linux images/Trivy/Compose проверены 18.10; внешний production-контур остаётся условием разблокировки. |
| FR-08 | P2 | FRONTEND-REDESIGN-01 | planned | Необязательное продолжение frontend; исходные критерии и границы — [план redesign](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/frontend-redesign-plan.md). Не закрыто очисткой. |
| DOC-CLEANUP-02 | P2 | DOC-VALUE-01 | done | Сократить историю, перенести полезные сведения и удалить заменённые отчёты; сохранить открытые требования и тестовые зависимости; links/UTF-8/diff/secret scan. |
| EXT-STEPUP-01 | P0 | OIDC/MFA/SDK, PostgreSQL, frontend | done | Реализован opt-in cross-application hosted step-up с password/TOTP/Passkey/комбинированными политиками, transaction binding, one-use server redemption, SDK/UI/тестами и self-audit. Матрица, миграция0015, SDK0.3.0 и локальные коммиты зафиксированы; production activation не входит. |
| MFA-DEFAULT-ADMIN-01 | P0 | EXT-STEPUP-01, PostgreSQL, frontend, SDK, EC2 | done | Default-on TOTP/Passkey/Recovery, обязательная MFA администратора, session assurance, recovery при TOTP/Passkey, non-destructive EC2 migration, OIDC role assurance, тесты и self-audit. Начало 2026-10-26T14:52:11+03:00; код `4857672`, ветка new/default-on-mfa-admin-policy. Production не изменялся; точные результаты — [acceptance](acceptance.md). |

Внешние SES/Gmail/Sentry, sender registration, multi-replica load и приватный owner review исторических credentials остаются условиями общей приёмки; [матрица и ограничения](acceptance.md), [безопасность](security.md). Их исторические ID/статусы/времена доступны по исходному плану и журналу, нового PASS нет. Остальные прежние незакрытые локальные/CI checkpoints требуют сверки с более поздним evidence перед возобновлением, а не автоматического выполнения старого плана.

## Последние завершённые результаты

| ID | Статус и время | Результат / критерий |
| --- | --- | --- |
| SEC-REMED-20261007-R1–R5 | done; начало 2026-10-07T02:18:09.9145364+03:00, завершение 2026-10-18T16:13:56+03:00 | Локальная реализация и обязательный retest; [приёмка](acceptance.md), ADR-0023. Это не production acceptance. |
| SEC-REMED-PR-01 | done; 2026-10-18T16:13:56+03:00 — 2026-10-18T16:15:08+03:00 | Commit f4b5fe5/push/PR13; merge уже присутствует в базе 7d1585e. Remote CI merge SHA здесь не проверен. |
| CI-FRONTEND-PR13-01 | done; 2026-10-18T13:32:36+00:00 — 2026-10-18T13:34:27+00:00 | Исправлен release libexpat pin, локальные typecheck/release build успешны; подробности в журнале. |
| DOC-REFRESH-01 | done; 2026-10-06T18:26:50.1134193+03:00 — 2026-10-06T19:01:30.930078+03:00 | Сверка документации и локальные проверки завершены; исторический акт доступен по ссылке приёмки. |
| DOC-VALUE-01 | done; 2026-10-20T02:42:56.2497535+03:00 — 2026-10-20T02:44:57.7269077+03:00 | Классифицированы 66 Markdown, код и зависимости кандидатов сверены, 19 ссылок проверены. Разовый отчёт удалён после исполнения рекомендаций в DOC-CLEANUP-02. |

## Исторический реестр TASK

Следующая таблица сохраняет первоначальные ID, зависимости, статусы и время. Это история соответствующего этапа: например, прежнее email default-off заменено ADR-0008. Критерии и позднейшие поправки читаются в исходном плане/журнале, не как новые результаты текущей ревизии.


| ID | Требования | Наименование | Приоритет | Зависимости | Статус | Начало | Завершение |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-001 | DOC-TRACK-01..07 | Создание системы трекинга разработки (`docs/plan.md`, `docs/worklog.md`, `docs/status.md`) и фиксация GOAL | P0 | — | done | 2026-09-24T11:35:00+03:00 | 2026-09-24T11:36:00+03:00 |
| TASK-002 | ARCH-01..06, SSO-01..08, SEC-FLAG-01..07, ГОСТ 19 | Проектирование архитектуры, модели данных, модели угроз, ADR и профиля стандартов | P0 | TASK-001 | done | 2026-09-24T11:36:00+03:00 | 2026-09-24T11:38:00+03:00 |
| TASK-003 | VER-01..03, CI-01..02, REL-01..03, CD-01..03 | Система версионирования (`VERSION`, скрипт бампа), GitHub Actions CI/Release и шаблон CD | P0 | TASK-001 | done | 2026-09-24T11:38:00+03:00 | 2026-09-24T11:40:00+03:00 |
| TASK-004 | ARCH-01..04, ARCH-06, USR-01..03 | Каркас FastAPI бэкенда, настройки, PostgreSQL модели SQLAlchemy, миграции Alembic и bootstrap администратора | P0 | TASK-002, TASK-003 | done | 2026-09-24T11:40:00+03:00 | 2026-09-24T11:51:00+03:00 |
| TASK-005 | ARCH-03..05, USR-01, SEC | Ядро сессий, парольный вход Argon2id, CSRF-защита, host-only cookies, аудит событий | P0 | TASK-004 | done | 2026-09-24T11:51:00+03:00 | 2026-09-24T11:53:00+03:00 |
| TASK-006 | SSO-01..07 | Реализация OIDC-провайдера: Discovery, JWKS, Authorization Code + PKCE S256, Token, UserInfo, Revocation, Logout | P0 | TASK-005 | done | 2026-09-24T11:53:00+03:00 | 2026-09-24T11:55:00+03:00 |
| TASK-007 | SEC-FLAG-01..07 | Реализация 4 отложенных возможностей (TOTP, WebAuthn Passkey, Recovery codes, Email verification) с отключением по умолчанию | P0 | TASK-005, TASK-006 | done | 2026-09-24T11:55:00+03:00 | 2026-09-24T12:01:00+03:00 |
| TASK-008 | UI-01..04, USR-01..03 | REST API личного кабинета пользователя и административной панели (RBAC, управление клиентами, сессиями, пользователями) | P1 | TASK-006, TASK-007 | done | 2026-09-24T12:02:00+03:00 | 2026-09-24T12:03:00+03:00 |
| TASK-009 | ARCH-05, UI-01..04 | Фронтенд на React + TypeScript (кабинет, аутентификация, MFA, админка) на русском языке | P1 | TASK-008 | done | 2026-09-24T12:10:00+03:00 | 2026-09-24T12:16:40+03:00 |
| TASK-010 | SDK-01..06 | Разработка Python SDK `alxprgs-sso` и двух демонстрационных клиентов OIDC | P1 | TASK-006 | done | 2026-09-24T12:04:00+03:00 | 2026-09-24T12:09:00+03:00 |
| TASK-011 | SSO-01..08, SEC-FLAG-01..07, ARCH-04 | Комплексные тесты: интеграционные на PostgreSQL, негативные OIDC/MFA, race conditions, RBAC | P0 | TASK-007, TASK-010 | done | 2026-09-24T12:19:30+03:00 | 2026-09-24T12:25:30+03:00 |
| TASK-012 | ARCH-04, ARCH-06, OPS | Эксплуатационный контур: Docker Compose, скрипты backup/restore БД, ротация ключей | P1 | TASK-004, TASK-007 | done | 2026-09-24T12:17:00+03:00 | 2026-09-24T12:19:15+03:00 |
| TASK-013 | Раздел 5 GOAL, ЕСПД | Русскоязычная документация по структуре ГОСТ 19.xxx (ТЗ, описание программы, ПМИ, руководства), README, ADR | P1 | TASK-002..TASK-012 | done | 2026-09-24T12:25:45+03:00 | 2026-09-24T12:26:50+03:00 |
| TASK-014 | Раздел 8 GOAL | Итоговая приёмка, проверка всех критериев, формирование матрицы `docs/acceptance.md` и release dry-run | P0 | TASK-001..TASK-013 | done | 2026-09-24T12:27:00+03:00 | 2026-09-24T12:28:40+03:00 |
| TASK-015 | GOAL-02 | Постановка и декомпозиция следующей цели `GOAL-02-registration-and-setup.md` | P0 | TASK-014 | done | 2026-09-24T17:11:12+03:00 | 2026-09-24T17:14:06+03:00 |
| TASK-016 | REG-02, SETUP-05, SETUP-06 | Проектирование модели состояния системы (ADR 0005, модель `SystemConfiguration`, миграция Alembic) | P0 | TASK-015 | done | 2026-09-24T17:23:00+03:00 | 2026-09-24T17:25:00+03:00 |
| TASK-017 | REG-02..08, TEST-REG-01..04 | Бэкенд: эндпоинт регистрации пользователей, управление режимом, аудит и rate limiting | P0 | TASK-016 | done | 2026-09-24T17:25:00+03:00 | 2026-09-24T17:29:00+03:00 |
| TASK-018 | SETUP-03..07, SETUP-10, TEST-SETUP-01..03 | CLI-мастер первого запуска (`bootstrap_admin`) с атомарной инициализацией и выбором режима | P0 | TASK-016, TASK-017 | done | 2026-09-24T17:29:00+03:00 | 2026-09-24T17:32:00+03:00 |
| TASK-019 | SETUP-01, SETUP-02, SETUP-04, SETUP-08, SETUP-09, TEST-SETUP-04 | Скрипты первого запуска (`start.ps1`, `start.sh`) и конфиг Compose (loopback, корректные переменные) | P0 | TASK-018 | done | 2026-09-24T17:32:30+03:00 | 2026-09-24T17:36:00+03:00 |
| TASK-020 | REG-01, REG-03, TEST-UI-01 | Фронтенд: страница регистрации, ссылки на входе и переключение режима в админке | P1 | TASK-017 | done | 2026-09-24T17:36:30+03:00 | 2026-09-24T17:40:00+03:00 |
| TASK-021 | TEST-REG-01..04, TEST-SETUP-01..04, TEST-UI-01 | Набор тестов регистрации, мастера запуска, безопасности, коллизий и гонок | P0 | TASK-017..TASK-020 | done | 2026-09-24T17:40:30+03:00 | 2026-09-24T17:41:30+03:00 |
| TASK-022 | Раздел 6, 7 GOAL-02, CI-01, VER-01..03 | Синхронизация версий (0.2.0), CI, ЕСПД, README и приёмочная матрица `docs/acceptance-registration-setup.md` | P0 | TASK-016..TASK-021 | done | 2026-09-24T17:42:00+03:00 | 2026-09-24T17:50:00+03:00 |
| TASK-023 | GOAL-03, Section 1 | Постановка цели и требований полного тестирования и исправлений (`GOAL-03-testing-and-fixes.md`) | P0 | TASK-022 | done | 2026-09-24T18:02:38+03:00 | 2026-09-24T18:05:38+03:00 |
| TASK-024 | QA-01 | Аудит тестового набора, инвентаризация тестов/моков, подготовка плана и реестра дефектов | P0 | TASK-023 | done | 2026-09-24T18:07:07+03:00 | 2026-09-24T18:12:00+03:00 |
| TASK-025 | QA-02 | Изолированный тестовый контур PostgreSQL, разделение unit и integration, устранение autouse get_db mock | P0 | TASK-024 | done | 2026-09-24T18:12:00+03:00 | 2026-09-24T18:18:00+03:00 |
| TASK-026 | QA-03, QA-04 | Проверка чистого и повторного запуска в Docker Compose, обработка сбоев и интерактивный мастер | P0 | TASK-025 | done | 2026-09-24T18:20:00+03:00 | 2026-09-24T18:35:00+03:00 |
| TASK-027 | QA-05, QA-06 | Интеграционные тесты регистрации, паролей, сессий, RBAC, cookies и CSRF на реальной PostgreSQL | P0 | TASK-025 | done | 2026-09-24T18:35:00+03:00 | 2026-09-24T18:45:00+03:00 |
| TASK-028 | QA-07 | Интеграционные тесты OIDC протокола с двумя клиентами, PKCE, ротации refresh и сессий SSO | P0 | TASK-027 | done | 2026-09-24T18:45:00+03:00 | 2026-09-24T18:55:00+03:00 |
| TASK-029 | QA-08 | Тестирование 4 отложенных возможностей: Default-off изоляция и Enabled профиль (TOTP, WebAuthn, Recovery, Email) | P0 | TASK-027 | done | 2026-09-24T18:55:00+03:00 | 2026-09-24T19:02:00+03:00 |
| TASK-030 | QA-09, QA-10 | Тестирование параллелизма, гонок на транзакциях PostgreSQL, rate limiting и отказоустойчивости | P0 | TASK-028, TASK-029 | done | 2026-09-24T19:02:00+03:00 | 2026-09-24T19:08:00+03:00 |
| TASK-031 | QA-11 | Разработка и запуск E2E Playwright тестов для фронтенда React с живым бэкендом | P1 | TASK-028, TASK-029 | done | 2026-09-24T19:08:00+03:00 | 2026-09-24T19:15:00+03:00 |
| TASK-032 | QA-12 | Тестирование Python SDK в изолированном venv из чистого wheel без доступа к backend | P1 | TASK-028 | done | 2026-09-24T18:55:00+03:00 | 2026-09-24T19:04:00+03:00 |
| TASK-033 | QA-13 | Тестирование миграций Alembic с нуля и скриптов backup/restore на отдельной БД | P1 | TASK-025 | done | 2026-09-24T19:04:00+03:00 | 2026-09-24T19:10:00+03:00 |
| TASK-034 | QA-14 | Настройка и проверка CI в GitHub Actions, dry-run релиза, аудит зависимостей и изоляция CD | P1 | TASK-030..TASK-033 | done | 2026-09-24T19:08:00+03:00 | 2026-09-24T19:20:00+03:00 |
| TASK-035 | QA-15, Section 8 GOAL-03 | Итоговая приёмка, сведение матрицы `acceptance-testing.md`, актуализация документации | P0 | TASK-024..TASK-034 | done | 2026-09-24T19:20:00+03:00 | 2026-09-24T19:25:00+03:00 |
| TASK-036 | GOAL-04 | Постановка цели GOAL-04 и отправка коммита `2c1de5b` с фиксацией baseline CI | P0 | TASK-035 | done | 2026-09-24T19:25:00+03:00 | 2026-09-24T19:30:36+03:00 |
| TASK-037 | G4-DB | Защита данных при тестах: `TEST_DATABASE_URL`, маскирование DSN, маркер владения, предотвращение TRUNCATE/DROP рабочей БД | P0 | TASK-036 | done | 2026-09-24T23:14:00+03:00 | 2026-09-24T23:18:00+03:00 |
| TASK-038 | G4-EMAIL | Сквозной цикл подтверждения email: регистрация -> отправка -> подтверждение -> вход неподтвержденным пользователем без обхода политики | P0 | TASK-037 | done | 2026-09-24T23:18:00+03:00 | 2026-09-24T23:27:00+03:00 |

| TASK-039 | G4-PASSKEY | Полный WebAuthn lifecycle в браузере: регистрация Passkey, повторный вход, множественные ключи, удаление, негативные проверки | P0 | TASK-038 | done | 2026-09-24T23:28:00+03:00 | 2026-09-25T00:01:00+03:00 |
| TASK-040 | G4-LIMITS | Межпроцессный rate limiting и доверенные proxy: многопроцессная изоляция, запрет обхода через `X-Forwarded-For` | P0 | TASK-037 | done | 2026-09-25T00:02:00+03:00 | 2026-09-25T00:12:00+03:00 |
| TASK-041 | G4-CI | Исправление сбоев GitHub Actions CI (SDK collection, healthcheck) и локальная верификация workflow | P0 | TASK-037..TASK-040 | done | 2026-09-25T00:13:00+03:00 | 2026-09-25T00:20:00+03:00 |
| TASK-042 | Раздел 7 GOAL-04 | Итоговая приёмка GOAL-04, оформление `docs/acceptance-goal-04.md`, доказательства и статус | P0 | TASK-037..TASK-041 | done | 2026-09-25T00:21:00+03:00 | 2026-09-25T00:24:00+03:00 |
| TASK-056 | GOAL-07 | Постановка ночной кампании стабильности GOAL-07 | P0 | — | done | 2026-09-25T05:10:35+03:00 | 2026-09-25T05:13:04+03:00 |
| TASK-057 | G7-START | Локализация и исправление падения frontend preview в CI run 36084939672 | P0 | TASK-056 | done | 2026-09-25T05:14:36+03:00 | 2026-09-25T05:25:00+03:00 |
| TASK-058 | G7-BOOT | Повторяемость чистого запуска и смены профилей (5 циклов, 40 E2E проверок) | P0 | TASK-057 | done | 2026-09-25T05:25:00+03:00 | 2026-09-25T05:32:00+03:00 |
| TASK-059 | G7-SOAK | Длительная 20-минутная проверка стабильности с телеметрией и Chromium smoke | P0 | TASK-058 | done | 2026-09-25T05:42:38+03:00 | 2026-09-25T06:03:14+03:00 |
| TASK-060 | G7-RACE | Конкурентная одноразовость и детекция replay на PostgreSQL (baseline) | P0 | TASK-058 | done | 2026-09-25T05:39:00+03:00 | 2026-09-25T05:41:30+03:00 |
| TASK-061 | G7-RECOVER, G7-MIGRATE | Тестирование устойчивости к сбоям, backup/restore и миграции чистой БД | P0 | TASK-058 | done | 2026-09-25T05:41:30+03:00 | 2026-09-25T05:42:15+03:00 |
| TASK-062 | G7-FINAL | Итоговая документация, регламент overnight.md, приемочный акт GOAL-07 | P0 | TASK-057..TASK-066 | done | 2026-09-25T05:42:30+03:00 | 2026-09-25T07:20:00+03:00 |
| TASK-063 | G7-RACE-FIX | Исправление объема конкурентных проверок: 10 попыток на каждый сценарий (50 тестов) | P0 | TASK-060 | done | 2026-09-25T06:20:00+03:00 | 2026-09-25T06:35:00+03:00 |
| TASK-064 | G7-MIGRATE-DATA | Верификация обновления существующей БД с данными 0001 -> 0002 и живым входом | P0 | TASK-061 | done | 2026-09-25T06:35:00+03:00 | 2026-09-25T06:50:00+03:00 |
| TASK-065 | G7-SOAK-RSS | Замер Working Set реального uvicorn worker процесса и повторный 20-мин soak-тест | P0 | TASK-059 | done | 2026-09-25T06:50:00+03:00 | 2026-09-25T07:15:00+03:00 |
| TASK-066 | G7-CRITERIA | Ужесточение критериев надежности раннера и модульное тестирование (10 тестов) | P0 | TASK-065 | done | 2026-09-25T07:05:00+03:00 | 2026-09-25T07:12:00+03:00 |

---


## Другие исторические ID

Подробности завершённых рефакторингов, CI-исправлений, миграционных экспериментов и промежуточных поручений убраны из текущего плана. Для каждого ID ниже критерии, фактическое время, прежние статусы и позднейшие уточнения сохранены в [исходном плане](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/plan.md) и [журнале](worklog.md):

`PROJECT-PR-01`, `UI-LAYOUT-01`, `FRONTEND-REDESIGN-01`, `PRIVACY-01`, `WEB-UI-01`, `COMMIT-NEW-01`, `PR-NEW-01`, `REVIEW-PR-02-01`, `REVIEW-CI-02-01`, `PR-FIX-02`, `CI-SES-01`, `CI-SES-02`, `UI-DELETE-01`, `AUDIT-PROD-01`, `AUDIT-REMEDIATION-01`, `BRANCH-PR-01`, `PR5-CI-01`, `EMAIL-RESEND-01`, `WEB-ROBOTS-01`, `WEB-SEO-01`, `WEB-UTF8-01`, `WEB-PERF-01`, `UI-THEME-FOOTER-01`, `BUILD-PERF-01`, `BUILD-PERF-PR-01`, `BRANCH-CLEANUP-01`, `DOC-CLEANUP-01`, `MERGE-DOCS-01`, `DOC-REFRESH-01`, `DOC-VERSION-LOCK-01`, `DOC-REFRESH-PR-01`, `SEC-AUDIT-20261007`, `SEC-REMED-20261007`, `CI-FRONTEND-PR13-01`.

Дополнительные исторические TASK-ID (критерии и исходные статусы доступны по той же ссылке): `TASK-043`, `TASK-044`, `TASK-045`, `TASK-046`, `TASK-047`, `TASK-048`, `TASK-049`, `TASK-050`, `TASK-051`, `TASK-052`, `TASK-053`, `TASK-054`, `TASK-055`, `TASK-067`, `TASK-068`, `TASK-069`, `TASK-070`, `TASK-071`, `TASK-072`, `TASK-073`, `TASK-074`, `TASK-075`, `TASK-076`, `TASK-077`, `TASK-078`, `TASK-079`, `TASK-080`, `TASK-081`, `TASK-082`, `TASK-083`, `TASK-084`, `TASK-085`, `TASK-086`, `TASK-087`, `TASK-088`, `TASK-089`, `TASK-090`, `TASK-091`, `TASK-092`, `TASK-093`, `TASK-094`, `TASK-095`, `TASK-096`, `TASK-097`, `TASK-098`, `TASK-099`, `TASK-100`, `TASK-101`, `TASK-102`, `TASK-103`.

## EXT-STEPUP-01: cross-application transaction step-up

Начало: 2026-10-26T13:08:40.0521508+03:00; исполнитель DeepSeek Harness; P0. База: `93c0fad7f92fd2ba8a4b860986fe52e8c3985234`, ветка `new/external-step-up-authentication`.

План: (1) изучить существующие reauth/WebAuthn/OIDC/SDK и зафиксировать переиспользование; (2) ADR вариантов A/B/C и assurance policy; (3) PostgreSQL state/endpoints/client policy/migration; (4) hosted UI; (5) SDK 0.3.0 и reference RP; (6) unit/PG/component/SDK/static проверки; (7) adversarial self-audit и regression; (8) docs/version/changelog/локальные коммиты. Production-флаги/БД/DNS/push/merge/release/publication не входят.

Критерий готовности: существующий OIDC login и внутренний reauth не сломаны; step-up принимает только разрешённые assurance/факторы и отклоняет wrong subject/client/action/payload/expiry/replay/session/revision; proof одноразовый и короткоживущий; SDK wheel проверен в изоляции; тестовая матрица и self-audit зафиксированы.

Завершение: 2026-10-26T14:21:34.5739392+03:00. Локальные коммиты d25d8ca, e9a832d, 0a36c1d, 8c38d78, a41f5f5 и финальный fix/документация; фактический HEAD — в [статусе](status.md). Проверки и ограничения — [приёмка](acceptance.md). Production flags/DB/deploy/release не менялись.

## DOC-CLEANUP-02: выполнение

Начало: 2026-10-20T02:46:26.6291142+03:00; исполнитель Codex. Завершение: 2026-10-20T02:49:55+03:00. Удалены SECURITY_AUDIT.md и docs/audit/security-remediation-20261018.md после переноса действующих сведений; разовый незакоммиченный documentation-value-review.md также удалён. Сокращены plan/acceptance/index/defects/checklist/ADR/CodeScene chronology, обновлён status. UTF-8:64 Markdown, 292 локальные ссылки/0 отсутствующих, 9 исторических Git targets существуют; secret self-test PASS,126 candidates/0new, baseline неизменён. Финальный diff --check выполняется после этой записи. Runtime и remote CI не запускались. Продолжение: review diff; открытая production-приёмка и DOC-VERSION-LOCK-01 сохранены.

## DOC-CLEANUP-PR-01 — PR очистки документации
- P2; in_progress; начало: 2026-10-20T02:51:20.8409615+03:00; исполнитель: Codex; зависит от DOC-CLEANUP-02.
- План: итоговый diff/проверки → commit → push → PR в main и фиксация ссылки.
- Готовность: изменения сохранены и отправлены, PR создан, проверки отражены без объявления remote CI PASS.

## SSO-SEC-0002 / #16
P1; in_progress; начало 2026-10-20T16:05:11.3295866+03:00; Codex; независимая main7555f47. План: атомарный отзыв всех OIDC refresh/code грантов при успешном self-service revoke/logout, сохранить выбранные browser sessions и security_revision; проверить ownership, logout API/OIDC и refresh/code. Готовность: PG regression/существующие lifecycle, PR+комментарий. Offline JWT остаётся до exp.

SSO-SEC-0002 done (2026-10-20T16:07:24.3035665+03:00): PG6+10PASS, ownership/lock orders/JWT scope подтверждены; PR публикация далее.
## SEC-ISSUES-20261020
Начало: 2026-10-20T16:00:07.3287809+03:00; Codex; P1; база main7555f47. SSO-SEC-0001–0006 (#15–20): in_progress. План: полные отчёты/повторный аудит → сверка main/PR → regression → исправление → PostgreSQL/статические проверки → независимые new/ ветки и PR → комментарии issues. Готовность каждого: устранена подтверждённая первопричина, проверки сохранены; иначе доказательный комментарий без фиктивного PR. Production/нагрузка/merge исключены.

SSO-SEC-0001 done (2026-10-20T16:03:30.6105628+03:00): критерий source isolation/PKCE/replay/revoke подтверждён PG1+10; публикация PR далее. SSO-SEC-0002–0006 остаются in_progress.

SEC-ISSUES-20261020 CI follow-up: общий image pin исправлен, независимая ветка сохранена; обязательный scan/CI pending.

## SEC-MERGE-20261020
P1; in_progress; начало 2026-10-20T20:32:43.1105797+03:00; Codex. По прямому поручению владельца слить PR21–26 в main, разрешая конфликты без потери шести security-исправлений. PR21 уже merged при первичной проверке. План: последовательные merge main в PR-ветки, проверка конфликтов и целевые regression, push, обязательный CI, merge с проверкой SHA. Готовность: все6merged, совместные проверки и точные результаты записаны. Production/deploy не входят.

## SSO-SEC-0003 / #17
P1; done; начало 2026-10-20T16:09:15.4876516+03:00; Codex; main7555f47. План: единый start/pending/mail путь для всех identities, collision только после mailbox proof; existing User/credentials неизменны; PG контракт и сохранение uniqueness/confirmation/quotas. Старые assertions409 заменить по изменённому security-требованию, сохранив негативное покрытие. Готовность: проверки/отдельный PR/комментарий.

SSO-SEC-0003 done (2026-10-20T16:10:59.2619568+03:00): PG/unit20 + усиленный collision1PASS, публичный status oracle устранён, uniqueness/consent/quotas сохранены. Далее отдельный PR и #18–20.

SEC-ISSUES-20261020 CI follow-up: общий image pin исправлен, независимая ветка сохранена; обязательный scan/CI pending.

SSO-SEC-0003 follow-up in_progress (2026-10-20T16:52:08.5777631+03:00): дополнительные repeat-ID/MAX_SENDS/mail-error oracles устранить единым start-путём для всех identities; коллизии разрешать только после mailbox proof в confirm. Это предусмотренная issue альтернатива. Background delivery/canonical IDs не нужны, quotas/503transport semantics сохранить. Критерий: повторныеID/5sendcap/ошибкаSMTP одинаковы, existing User/credentials неизменны, validmailproofcollision отказ, mandatoryemail/newregistration работают.

SSO-SEC-0003 uniform follow-up done (2026-10-20T16:56:04.6698984+03:00):26PASS, repeat-ID/sendcap/providerfailure пути унифицированы; ADR0028/API/security актуальны. PR23 finalCI после push; другие5PR finalCI success. Все6PR/issue comments созданы, merge/manualclose не выполнялись.

SEC-ISSUES-20261020 done (2026-10-20T17:02:01.9691227+03:00): все6отдельных PR/issue comments созданы, все6finalfunctionalCI SUCCESS; матрица точныхSHA/ограничения вacceptance. Дальше owner review/merge, не выполняются автоматически. Documentation-only checkpoint проходит обычный CI отдельно.

## SSO-SEC-0004 / #18
P1; in_progress; начало 2026-10-20T16:12:56.2905732+03:00; Codex; независимая main7555f47. План: bounded process aggregation анонимных action_denied до background/DB; periodic batch flush60с и shutdown, bounded retry при ошибке БД. Сохранить authenticated audit/login_failed и retention90дней. Готовность: малые серии401/403/429, counts/cardinality/failure/actor tests, PR+comment.

SSO-SEC-0004 done (2026-10-20T16:17:10.7190217+03:00):20PASS targeted, bounded writes/counts/failures/actor evidence; PR далее.

SEC-ISSUES-20261020 CI follow-up: общий image pin исправлен, независимая ветка сохранена; обязательный scan/CI pending.

## SSO-SEC-0005 / #19
P1; in_progress; начало 2026-10-20T16:18:36.9114901+03:00; Codex; main7555f47. План: browser-held HttpOnly flow secret/hash в pending; повторный start вращает proof и инвалидирует чужой browser/старые email secrets; resend/confirm требуют flow proof. Gmail shortcut — GoTo/ViewAction в исходный browser; legacy server action тоже требует browser proof. Mailbox-mark/complete отвергнуты (ADR0026). Legacy pending fail-closed. Миграция0014, ADR, API/UI, regression original/reverse/interleaving/replay. Готовность: PG+frontend+static, отдельный PR/comment.

SSO-SEC-0005 done (2026-10-20T16:30:27.5799474+03:00): final46PASS, frontend40/types/lint/build/static65/secret0newPASS; mandatory browser+mail proofs на всех путях и legacy отказ проверены. PR публикация далее; #20 остаётся in_progress.

SSO-SEC-0005 CI follow-up: schema guard0014 + ownedCompose/migration regressions выполнены; общий libx11pin внесён, повтор CI pending.

## SSO-SEC-0006 / #20
P1; in_progress; начало 2026-10-20T16:31:42.5772362+03:00; Codex; main7555f47. План: persistent source+identifier/source+account quotas5/60с с alias protection и source30/60с; bounded Argon2 admission16total/2source/2workers,429+RetryAfter вместо503 перегрузки; trusted-source context и cancellation reservation. Regression targeted lockout/aliases/spoofing и8requestburst с реальным Argon2+легитимным другим источником. Готовность: PG/unit/crypto/MFA/static, PR/comment. Distributed/NAT ограничения явно документировать.

SSO-SEC-0006 local done (2026-10-20T16:35:55.3927006+03:00):23PASS; отдельный PR далее. До завершения всех6PR исправить обнаруженные image/libx11 и schema-guard CI blockers, не ослабляя обязательные проверки.

SEC-ISSUES-20261020 CI follow-up: общий image pin исправлен, независимая ветка сохранена; обязательный scan/CI pending.

## SEC-ISSUES-20261020: итог реализации
Все SSO-SEC-0001–0006 реализованы, локально проверены и опубликованы: #15 PR21 (PG1+10), #16 PR22 (PG6+10), #17 PR23 (20+collision1), #18 PR24 (20), #19 PR25 (46+frontend40+migration/Compose), #20 PR26 (23+source scheduling6). Каждый issue получил комментарий. Общие image/schema CI blockers исправлены с сохранением guard/scan; PR25 finalcode CI success, остальные finalCI проверяются перед итоговым отчётом. Функциональных зависимостей междуPR нет; append-only документы при последовательном merge сверить вручную.

SEC-MERGE-20261020 checkpoint (2026-10-20T20:42:24.7276264+03:00): PR21/22merged; PR23CIjobsSUCCESS; PR24–26 продолжаются. Все6fixes локально совместимы,36combinedtestsPASS; единственный ручной codeconflict resend решён с дополнительным regression. До done остаются обязательныйCI и merge остальных PR.

SEC-MERGE-20261020 (2026-10-20T20:48:49.4847872+03:00): in_progress; PR21–25merged. До PR26merge исправить test teardown synchronization, не освобождать production slots раньше worker. Targeted6PASS; критерий оставшегося шага — CI новогоSHA success,merge26,проверка всех6GitHubstates.

## SEC-MERGE-20261020 — done

Начало: 2026-10-20T20:32:43.1105797+03:00; завершение: 2026-10-20T20:54:27.8702087+03:00; Codex. Критерий выполнен: PR21–26 merged, все6issues закрыты автоматически; каждый updated PR head прошёл обязательный CI. Code/docs конфликты разрешены, совместный regression добавлен, cancellation-test race исправлена без изменения защиты. Точные SHA/CI — [приёмка](acceptance.md). Следующий шаг: применять миграцию0014 при отдельном развёртывании; production/live email/load остаются отдельной приёмкой.

## DEPLOY-EC2-01
P1; in_progress; начало: 2026-10-25T16:16:15.9332703+03:00; Codex. Зависимости: Compose/CI/Resend. План: production topology/bootstrap → bundle/CD exact SHA → backup/renew/alerts → regression и инструкция AWS. Готовность: Spec Freeze v1 реализован, локальные и AWS-проверки записаны раздельно. Внешние действия выполняет владелец; сеть не меняем.

DEPLOY-EC2-01 checkpoint 2026-10-25T16:57:52.0663676+03:00: локальная реализация и проверки готовы; overall in_progress. Критерии локально:43unit+9CIpolicyPASS, actualUbuntuTLS/flock/OpenSSL и actualPGbundle/backuprestorePASS; evidence вacceptance. Точка продолжения: владелец выполняет docs/ec2-deployment.md начиная с bootstrap, затем передаёт обезличенный результат для сопровождения. Production/readiness/email/ACME/GitHublive пока не засчитаны.

DEPLOY-EC2-01 2026-10-25T17:11:30.2215594+03:00: окончательный code c358413 включает collision-safe backup с4regression и fsync.47targeted+9CIpolicyPASS; exactSHA bundle/actualPG backuprestore и UbuntuTLS/config/flockPASS. Локальные критерии реализации выполнены, общий статус in_progress до пользовательской AWS-проверки; команды и ограничения вacceptance/ec2-deployment.

DEPLOY-EC2-01 2026-10-25T17:13:06.0638441+03:00: blocked на внешней AWS-приёмке. Локальная реализация и проверки завершены; три последовательных goal-turn упираются в отсутствие результата владельческого bootstrap. Условие разблокировки: владелец выполняет раздел2 docs/ec2-deployment.md и сообщает успех/обезличенную ошибку. Повторные локальные тесты без изменений не требуются.

DEPLOY-EC2-01 2026-10-25T17:27:42.1509866+03:00: AWS bootstrap начат владельцем, прежнее ожидание запуска заменено наблюдаемым blocked — Certbot HTTP-01 TCP80 connect timeout. Условие продолжения: доступность HTTP challenge снаружи и повторный bootstrap; SG/host firewall пока не проверены, серверная конфигурация сохраняется.

DEPLOY-EC2-01 manual-CD 2026-10-25T18:01:01.0734739+03:00: in_progress по прямому поручению владельца. План: workflow_dispatch только main без общего CI, сохранить автоматический successful-CI gate, exactSHA/freshness/concurrency/highwater и обязательный transport test; regression матрица событий и документация. Готовность: ручной путь реализован и локально проверен, отсутствие общегоCI не объявляется PASS.

DEPLOY-EC2-01 manual-CD 2026-10-25T18:03:29.4349911+03:00: done в части реализации ручного запуска.47targetedPASS2.41s; инструкция GitHub Actions Runworkflow/main добавлена. Внешняя EC2/CI-приёмка остаётся отдельной и незакрытой.

DEPLOY-EC2-01 runner-workspace 2026-10-25T18:11:24.9532850+03:00: in_progress. По логу job121205110397 доказано: отсутствует artifacts parent на чистом CD runner. План: создавать parent перед private_directory без ослабления ACL/отказа reuse, regression fresh checkout, targeted проверки. Критерий: подготовка workspace проходит при отсутствующем artifacts и сохраняет защиту.

DEPLOY-EC2-01 runner-workspace 2026-10-25T18:14:46.1568259+03:00: done локально.53targetedPASS5.95s и actualLinux mode0700/reuse/symlinkPASS. Исправлена подготовка clean runner; дальнейший новый CD run на обновлённом main ещё не выполнен.

DEPLOY-EC2-01 image-portability 2026-10-25T18:45:19.5188623+03:00: in_progress. AWS load успешен, daemon не знает обоих manifest imageID; backend виден под иным ID. План: переносимый export с tagged PostgreSQL и platform-specific identity, независимая проверка import между image stores, stage-safe диагностика, regression. Без подмены ожидаемых ID фактическими и без выключения integrity/SHA checks.

DEPLOY-EC2-01 image-portability 2026-10-25T19:41:38+0300: локально done, live-подтверждение ожидает новый CD run. Причина инцидента — containerd image store раннера (ID=digest манифеста, save=OCI) против классического store сервера (ID=config-digest). Реализовано: config-digest из парса images.tar (ground truth транспорта), pin классического store на раннерах CD/CI, тег alxprgs-sso-postgres, репетиция серверной проверки ID в transport-check, argv сбойной команды в ошибках ssoctl, ADR-0030, 8 regression-тестов; 42 targeted PASS, ruff check/format PASS. Пуш в main по прямому указанию владельца; критерий закрытия — зелёный CD run нового SHA и Deployed на сервере.

DEPLOY-EC2-01 image-portability 2026-10-25T20:22:00+0300: blocked на фактах с EC2. Коммиты 8095ad8+54e94c7: транспорт пересобран на config-digest из images.tar, раннеры CD/CI пинят классический store; CI job Verify CD Policy SUCCESS на реальном Docker. Ручной CD sequence 9 упал на сервере с прежним кратким сообщением старого ssoctl (обновление оператора — вручную bootstrap). Условие разблокировки: диагностика владельца с EC2 (docker version/info, повторный load, inspect manifest-ID) и по её результату — настройка демона/обновление оператора; отдельная задача — security-audit зависимости (undici npm; setuptools 84.1.0, filelock 4.2.1 pip; trivy image) для зелёного CI и автоматического CD.

DEPLOY-EC2-01 image-portability 2026-10-25T20:52:00+0300: done. Критерий выполнен: CD run 40218034347 зелёный, «Deployed 69794fb; sequence 11», публичная HTTPS/discovery проверка прошла внутри деплоя. Итог цепочки: containerd store раннера (8095ad8) → формат archives Docker 25+ (54e94c7) → containerd store Docker 29 на сервере (69794fb + настройка владельца). По DEPLOY-EC2-01 в целом остаются: sudo ssoctl admin владельцем, live-приёмка; отдельная плановая задача — обновление зависимостей ради зелёного CI (undici npm; setuptools 84.1.0, filelock 4.2.1 pip; trivy image) для возврата автоматического CD.
