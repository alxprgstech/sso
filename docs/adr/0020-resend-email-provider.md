# ADR 0020 — native Resend как третий email transport

> Сверка 06.10.2026: сохранено решение на дату принятия; это не новый результат приёмки. Действующий профиль: [архитектура](../architecture.md), [API](../api.md), [статус](../status.md).

- Дата: 2026-10-05. Статус: принято для EMAIL-RESEND-01 по Spec Freeze v1.

## Контекст и решение

Регистрация и подтверждение существующего аккаунта используют `verification_email.build_message/deliver_message`. SES и SMTP передают общий text/AMP/HTML MIME; очередей, fallback, delivery-state и webhook receivers нет. Имя `SESEmailDeliveryError` исторически используется и для SMTP. Эти интерфейсы и обе реализации сохраняются.

Добавлен `EMAIL_PROVIDER=resend` и отдельный async `resend_email` adapter. Ключ — только `Settings.RESEND_API_KEY` (`SecretStr`, исключён из repr и serialization). По прямому выбору владельца sender — `SMTP_FROM_EMAIL`, имя `ALXPRGS`; новые sender-настройки не вводятся. Ключ и sender валидируются при старте только для выбранного Resend. Default остаётся SMTP.

Используется уже закреплённый HTTPX 0.28.1: native `POST https://api.resend.com/emails`, Bearer, JSON, User-Agent, системная TLS verification, пятисекундные network timeouts и запрет redirects. Client создаётся на отправку и закрывается, либо передаётся caller-owned client для тестов. Это повторяет существующий HTTP-подход backend, не добавляет dependency и не требует глобального SDK key/client. Официальный Python SDK имеет async API, но для одного endpoint дополнительный SDK не даёт необходимой проекту возможности. Зависимости/locks не меняются.

Точные text/HTML тела декодируются из общего MIME; код, ссылка, escaping и Schema.org сохраняются. В опубликованном API нет AMP/raw MIME поля: AMP не передаётся через Resend. SES/SMTP продолжают передавать все три части. Текущий контракт не использует Reply-To/custom headers/attachments/tags; новые возможности не вводятся.

## Ошибки и безопасность

Адаптер использует существующий `SESEmailDeliveryError`: key/permission → `access_denied`; validation/rejection → `message_rejected`; rate/quota 429 → `quota_exceeded`; 5xx/network/timeout → `temporary_unavailable`; invalid JSON/ID → `invalid_response`; остальные отказы → `failed`. HTTP 403 `validation_error` включает ограничения домена/тестовых recipients. Исходные HTTP request/response и exception не сохраняются в ошибке; raw provider message никогда не логируется. Acceptance log содержит только проверенный canonical UUID; ID означает принятие API, не доставку.

Finite allowlists Sentry и аудита дополнены Resend; аудит также допускает используемую безопасную категорию `failed`. Остальная фильтрация сохраняется. Coroutine cancellation проходит без преобразования, клиент освобождается. Семантика 503 регистрации и нейтрального existing-account ответа не меняется. Retries и fallback не добавлены. Опциональная Resend идемпотентность (24 часа) не используется: существующий pipeline не повторяет HTTP submission, а пользовательский resend создаёт новые secrets.

## Альтернативы и границы

Resend через SMTP отклонён: требуется native API. Перестройка EmailSender/factory и миграция SES/SMTP отклонены как ненужные. Webhooks Resend существуют, включая delivery/bounce/complaint, но общий текущий контракт не принимает события; webhook subsystem не входит в задачу. Нового persistent delivery ID/state, API endpoints, DB migrations или auth policy нет. TLS SMTP и политика boto3 retry сохраняются.

## Источники

Проверены 05.10.2026: [HTTP/authentication/User-Agent](https://resend.com/docs/api-reference/introduction), [Send Email](https://resend.com/docs/api-reference/emails/send-email), [errors](https://resend.com/docs/api-reference/errors), [usage/rate limits](https://resend.com/docs/api-reference/rate-limit), [idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys), [domains](https://resend.com/docs/dashboard/domains/introduction), [events](https://resend.com/docs/webhooks/event-types), [official Python SDK async](https://github.com/resend/resend-python).

Проверки и ограничения: [приёмка Resend](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/acceptance-resend.md).
