# ADR 0009 — testmail.app как инфраструктура тестов

> Сверка 06.10.2026: сохранено решение на дату принятия; это не новый результат приёмки. Действующий профиль: [архитектура](../architecture.md), [API](../api.md), [статус](../status.md).

- Дата: 02.10.2026. Статус: принято владельцем, реализация TASK-103.
- Контекст: нужна настоящая проверка доставки и погашения verification code/link; SMTP capture не подтверждает SES delivery.
- Решение: Essential namespace, существующий SES raw MIME sender, общий Python GraphQL helper в tests/helpers, PostgreSQL fixtures и асинхронный JSON pipe для Playwright. Production runtime не импортирует helper. Settings наследует существующий pydantic-settings механизм; секреты — SecretStr, корневой игнорируемый .env / GitHub Secrets.
- Обычные тесты остаются offline/SMTP. Внешняя группа opt-in локально, обязательна на main, ручном main CI и release SHA; PR секретов не получает. Последовательный запуск; общая PostgreSQL исключает xdist. Без retries целого сценария и без ослабления rate limits/email/RBAC.
- Альтернативы: отдельный TS клиент дублирует parsing/polling; JSON API помещает ключ в URL; livequery требует 307 redirect loop; замена SES тестовым транспортом не проверяет доставку SES. Эти варианты отклонены.
- Последствия: зависимость от доступности двух провайдеров, расходы Essential/SES и отдельные credentials; отсутствие credentials и sandbox дают явную ошибку выбранной внешней группы. Live-приёмка пока заблокирована SES sandbox и отсутствующими testmail credentials/выделенной БД.
- Источники: [API](https://testmail.app/docs/), [GraphQL attachments](https://testmail.app/blog/email-testing-in-php-with-testmail/), [SES sandbox](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html).

Уточнение 03.10.2026 (CI-SES-01, GOAL CI-03): по прямому решению владельца main/manual-main CI пропускает внешний job без любого из двух AWS-ключей, с notice/summary и без признания live-приёмки успешной. Проверка наличия выполняется в отдельном job без checkout, основной SES job зависит от boolean output. Прямое обращение к secrets в job if не поддерживается GitHub Actions; использование step-only skip не дало бы всему job статус skipped. При доступных ключах прежние preflight/сценарии и failed outcomes сохранены. Явный run_email_tests=true, включая release, по-прежнему требует credentials. Это уточнение заменяет выше только обязательность запуска без AWS credentials в обычном main CI; доставка, sandbox и остальные защиты не меняются. Подробности: [инструкция](../testing/email.md).
