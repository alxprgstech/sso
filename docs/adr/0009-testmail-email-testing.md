# ADR 0009 — testmail.app как инфраструктура тестов

- Дата: 02.10.2026. Статус: принято владельцем, реализация TASK-103.
- Контекст: нужна настоящая проверка доставки и погашения verification code/link; SMTP capture не подтверждает SES delivery.
- Решение: Essential namespace, существующий SES raw MIME sender, общий Python GraphQL helper в tests/helpers, PostgreSQL fixtures и асинхронный JSON pipe для Playwright. Production runtime не импортирует helper. Settings наследует существующий pydantic-settings механизм; секреты — SecretStr, корневой игнорируемый .env / GitHub Secrets.
- Обычные тесты остаются offline/SMTP. Внешняя группа opt-in локально, обязательна на main, ручном main CI и release SHA; PR секретов не получает. Последовательный запуск; общая PostgreSQL исключает xdist. Без retries целого сценария и без ослабления rate limits/email/RBAC.
- Альтернативы: отдельный TS клиент дублирует parsing/polling; JSON API помещает ключ в URL; livequery требует 307 redirect loop; замена SES тестовым транспортом не проверяет доставку SES. Эти варианты отклонены.
- Последствия: зависимость от доступности двух провайдеров, расходы Essential/SES и отдельные credentials; отсутствие credentials и sandbox дают явную ошибку выбранной внешней группы. Live-приёмка пока заблокирована SES sandbox и отсутствующими testmail credentials/выделенной БД.
- Источники: [API](https://testmail.app/docs/), [GraphQL attachments](https://testmail.app/blog/email-testing-in-php-with-testmail/), [SES sandbox](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html).
