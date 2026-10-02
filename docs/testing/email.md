# Реальные email integration/E2E — testmail.app

TASK-103, ADR 0009. Это тестовая инфраструктура: FastAPI → общий verification MIME → существующий SES → testmail.app → Python GraphQL polling. Production services, схема БД и зависимости runtime не изменены. Unit tests используют MockTransport/fake SES; обычный browser suite сохраняет SMTP capture.

## Предварительные условия

1. Essential account testmail.app: получите API key и назначенный namespace в [console](https://testmail.app/console). Ограничьте key этим namespace. Адрес `namespace.tag@inbox.testmail.app` создаётся без регистрации mailbox.
2. SES production access в выбранном регионе, включённая отправка и verified sender domain. Sandbox не допускает произвольных уникальных получателей. Запрос production access выполняет владелец отдельно; helper AWS не меняет.
3. Выделенная PostgreSQL с миграциями и штатным fresh-test marker. Рабочая Compose БД не подходит. Guard запрещает очистку без marker/допустимого имени; SQLite не применяется.
4. Python с requirements-lock.txt и установленным backend, Node с `npm ci`, Chromium (`npx playwright install chromium`). Для runner frontend должен собраться; порты 8000/5173 должны быть свободны.

На 02.10.2026 наблюдался SES sandbox; testmail credentials и локальный TEST_DATABASE_URL отсутствовали. Реальная доставка и live flows ещё не приняты.

## Переменные

| Переменная | Секрет | Локально | GitHub Actions | Обязательность |
|---|---|---|---|---|
| TESTMAIL_API_KEY | да | корневой игнорируемый .env | Secret | внешняя группа |
| TESTMAIL_NAMESPACE | нет | .env | Variable | внешняя группа |
| TESTMAIL_TIMEOUT_SECONDS | нет | .env/env | Variable/default 120 | optional |
| TESTMAIL_POLL_INTERVAL_SECONDS | нет | .env/env | Variable/default 2 | optional |
| AWS_ACCESS_KEY_ID | credential | .env или стандартная AWS chain | Secret | CI |
| AWS_SECRET_ACCESS_KEY | да | .env или AWS chain | Secret | CI |
| AWS_SESSION_TOKEN | да | .env или AWS chain | Secret | временные credentials |
| SES_REGION | нет | существующие Settings | Variable/default us-east-1 | optional |
| SES_FROM_EMAIL / SES_FROM_NAME | нет | существующие Settings | Variables/default sso@alxprgs.tech / ALXPRGS | optional |
| TEST_DATABASE_URL | может содержать пароль | environment, отдельная test DB | service job | integration/E2E |
| PYTHON_BIN | нет | runner задаёт sys.executable | runner | прямой Playwright wrapper |

Settings наследует центральный `app.config.Settings`; тот же dotenv/environment precedence. Корневой .env читается независимо от cwd. Test-only поля не добавляются production Settings. API endpoint фиксирован: HTTPS GraphQL POST с Bearer header; ключ не попадает в URL/arguments. Не добавляйте настоящие значения в .env.example.

```dotenv
TESTMAIL_API_KEY=
TESTMAIL_NAMESPACE=
TESTMAIL_TIMEOUT_SECONDS=120
TESTMAIL_POLL_INTERVAL_SECONDS=2
```

TEST_DATABASE_URL должен быть явно экспортирован: pytest DB guard намеренно не читает его из dotenv. Используйте существующую инструкцию [тестовой БД](../../README.md) и scripts/init_fresh_ci_test_marker.py; не создавайте marker на существующей рабочей базе. Для локального marker применяются строгие ограничения скрипта `--local-fresh`.

## Запуск из корня репозитория

```text
python -m tests.helpers.testmail_cli preflight
pytest tests/integration/test_testmail_email_pg.py -m email_external --run-email-tests -x --tb=short
python scripts/run_e2e_suite.py --suite email
```

Обычный pytest всегда deselects email_external, даже с credentials. Явный запуск без key/namespace даёт UsageError до БД. `--showlocals` и xdist запрещены внешней группе: текущие PostgreSQL fixtures очищают общие таблицы. Integration teardown использует прежний DB guard и удаляет синтетические данные. Browser runner использует прежние seed/start/preflight/stop инструменты, отдельные временные pid/log файлы и finally cleanup. E2E seed содержит только вспомогательные аккаунты; проверяемый новый пользователь проходит настоящее подтверждение.

Email profile фиксирует SES, testing, REQUIRE_VERIFIED_EMAIL=true, обязательное email и три выключенных MFA-флага; DSN backend совпадает с TEST_DATABASE_URL. BASE_URL=http://localhost:8000, FRONTEND_URL=http://localhost:5173. Готовый standalone стенд можно проверить `cd frontend && npm run test:e2e:email`, задав PYTHON_BIN и правильный profile; предпочтителен runner.

## Покрытие и ожидание

Пять integration cases: регистрация code/link/resend; исходно неподтверждённый обычный пользователь code/link. Проверяются реальное письмо, отсутствие пользователя до подтверждения, неправильный OTP, preview без погашения, replay, verified login, обычная роль и отказ admin API. Browser cases независимо открывают регистрацию через admin UI с re-auth, подтверждают code/link и проверяют обычный кабинет; закрывают регистрацию в finally. Штатно 6 integration + 2 browser = 8 писем. Password reset/email login отсутствуют в бизнес-контракте и не добавлены.

From/To разбираются семантически; subject точный; проверяются text/HTML, username, 10 минут и сведения о запросе, ведущие нули шестизначного ASCII OTP, совпадение text/HTML ссылки, точные origin/port/path/mode и единственный token, отсутствие attachments. HTML parser не извлекает код из script/schema. Ссылка не открывается до проверки origin.

Каждый адрес содержит context hash + UUID128. Контекст включает workflow run/attempt/job/worker/test; повторный запуск создаёт новый адрес. Checkpoint фиксируется до send, хранит IDs и hashes содержимого уже полученных писем; последний исключает запоздалые копии SES при resend. Фильтр — namespace + exact tag + received timestamp с 5s overlap, затем recipient/ID/content. Sender Date не используется.

GraphQL polling livequery=false: monotonic deadline 120s, interval 2s+jitter, connect ≤5s/read ≤10s с ограничением оставшимся временем. Только read-запросы повторяются на network/5xx/429 (Retry-After), bounded backoff и общий deadline; auth/schema ошибки немедленны. Новая регистрация/отправка и целый test автоматически не повторяются. Browser timeout 180s, один worker, retries=0; bridge имеет собственный ограниченный timeout и завершает child. Увеличение poll timeout выше 120 требует согласовать browser timeout/bridge бюджет, иначе browser не сможет дождаться helper.

Публичная schema проверена read-only 02.10.2026: Email.to/from — String, timestamp — Float, headers — HeaderLine {key,line}; Attachment — отдельный тип. Доступ ключа к namespace и реальный доставленный ответ проверяются authenticated preflight/live acceptance, пока заблокированы. [Документация API](https://testmail.app/docs/), [attachments](https://testmail.app/blog/email-testing-in-php-with-testmail/).

## CI / release

Добавьте repository Secrets TESTMAIL_API_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY и при необходимости AWS_SESSION_TOKEN; Variables TESTMAIL_NAMESPACE и опциональные SES/poll параметры. Essential принят для проекта; следите за квотой писем и расходов.

Один job email-e2e обязателен на push main, ручном CI main и reusable release CI для точного tag SHA. На PR и ручных других ветках не запускается. Release вне main явно отвергается первым шагом до checkout, иначе пропуск email job мог бы оставить release build разрешённым. До Secrets проверяется принадлежность checkout SHA истории origin/main; install/build не получают ключи. Отдельный PostgreSQL service, миграции и fresh marker; API phase перед browser phase. Release явно передаёт четыре Secrets и run_email_tests=true, без inherit. Failure блокирует release build; missing credentials/sandbox не дают skip/continue-on-error. CD остаётся выключенным шаблоном.

IAM CI credentials выделенные: ses:SendEmail для sender identity с ses:FromAddress и ses:Recipients `namespace.*@inbox.testmail.app`; read-only preflight требует ses:GetAccount, ses:GetEmailIdentity, ses:GetConfigurationSet. GetAccount обычно требует Resource=*; identity/config-set permissions ограничивайте поддерживаемыми ресурсами. Проверяйте фактическую IAM policy в выбранном аккаунте; helper её не создаёт.

## Безопасность и диагностика

Backend child получает AWS chain, но не TESTMAIL_*; frontend preview/build не получает AWS_* / TESTMAIL_*. Python helper работает вне браузера и передаёт OTP/link только через private JSON pipe. TLS verification включена, redirects запрещены. Не включайте HTTPX/httpcore/botocore debug, environment dumps, pytest --showlocals или raw HTTP traces.

Внешние pytest failures сохраняют failed outcome, но убирают assertion locals/captured logs; безопасная EmailTestError различает timeout/API/контракт. Другие errors показывают только case/stage. Playwright trace/screenshot/video выключены, reporter не сохраняет errors/stdout/URLs/steps/attachments. Private CLI stderr преобразуется wrapper в фиксированную категорию timeout/authentication/contract/otp/link/content/configuration/helper; browser reporter сохраняет только эту категорию или browser/none, не текст ошибки. Job публикует только artifacts/email/{pytest,browser,runner}-summary.json по allowlist; raw server logs и test-results не загружаются. Temporary runner logs удаляются после остановки. Не загружайте произвольные локальные отчёты внешней группы как artifacts. GitHub masking — дополнительная защита, не замена отсутствию секретов в выводе.

.env игнорируется Git; `git check-ignore .env` и secret scanner проверяйте перед commit. Новые scanner findings требуют просмотра; реальный key не добавляйте в baseline. Детектор синтетического контроля остаётся обязательным. Используйте также secret scanning платформы, если доступно для закрытого репозитория.

| Сбой | Действие |
|---|---|
| Credentials required | заполнить локальный .env / GitHub Secrets и Variable, не отправлять ключ в issue/log |
| SES sandbox | владелец получает production access в нужном регионе; не менять transport/политику |
| GraphQL contract/auth error | проверить scope key и namespace; schema drift исправлять с offline regression test |
| Timeout | проверить SES acceptance/audit category, sender identity, account quotas, доступность провайдеров; не повторять send автоматически |
| Body/OTP/link mismatch | исследовать шаблон приватно; не печатать письмо/код/token; исправить первопричину |
| DB safety error | отдельная свежая test DB с корректным marker; не обходить guard |
| Cleanup failed | проверить собственный pidfile и владельца порта; не убивать чужой listener |

Delete API отсутствует, письма удаляются автоматически по retention Essential (1–3 дня); cleanup testmail не нужен. Paid API: избегайте устойчивых >5 req/s на key и >10 req/s на IP; текущий последовательный polling остаётся значительно ниже. Параллельные runs имеют разные mailbox; xdist потребует отдельную DB/backend на worker. Получение письма не доказывает отображение Gmail AMP/OTP cards. [Retention и лимиты](https://testmail.app/docs/), [тариф](https://testmail.app/pricing/).
