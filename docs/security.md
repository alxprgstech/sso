# Модель угроз и политики безопасности ALXPRGS SSO

- Обозначение документа: ALXPRGS.SSO.SEC-01
- Версия: 1.0.0
- Дата: 2026-09-24T11:38:00+03:00
- Статус: Утверждён

---

## 1. Введение

Настоящий документ определяет модель угроз, политики противодействия атакам и архитектурные инварианты безопасности системы ALXPRGS SSO.

---

## 2. Модель угроз (Threat Model) и меры защиты

| Идентификатор угрозы | Описание вектора атаки | Меры противодействия в ALXPRGS SSO | Ссылка на тесты |
| --- | --- | --- | --- |
| **THREAT-01**: Перебор паролей (Brute-force) | Массовый подбор учетных данных пользователей через эндпоинты входа. | 1. Rate limiting на базе IP и учетной записи в PostgreSQL/памяти.<br>2. Экспоненциальная задержка и временная блокировка после 5 неудачных попыток.<br>3. Фиксация события `login_failed` в аудите без раскрытия факта существования пользователя. | `tests/security/test_bruteforce.py` |
| **THREAT-02**: Перехват и подделка сессий (Session Hijacking / Fixation) | Кража идентификатора сессии через сеть, соседние поддомены или фиксация чужой сессии. | 1. Host-only cookies с префиксом `__Host-` (без атрибута `domain`).<br>2. Флаги `Secure`, `HttpOnly`, `SameSite=Lax`.<br>3. Ротация session token при успешной аутентификации.<br>4. Привязка сессии к User-Agent и IP (с лояльностью к смене мобильной подсети). | `tests/security/test_session_security.py` |
| **THREAT-03**: Межсайтовая подделка запросов (CSRF) | Выполнение несанкционированных действий от лица аутентифицированного пользователя через сторонний сайт. | 1. Заголовок `X-CSRF-Token`, проверяемый на бэкенде для всех мутирующих запросов (POST, PUT, DELETE, PATCH).<br>2. Cookie `SameSite=Lax` предотвращает передачу сессионных cookie в cross-site POST. | `tests/security/test_csrf.py` |
| **THREAT-04**: Межсайтовый скриптинг (XSS) и кража токенов | Внедрение стороннего JavaScript в интерфейс с целью хищения токенов. | 1. Запрет хранения Bearer токенов (Access/Refresh) в `localStorage`/`sessionStorage` браузера.<br>2. Сессионные cookie недоступны для JS (`HttpOnly`).<br>3. Строгие заголовки `Content-Security-Policy`, `X-Content-Type-Options: nosniff`. | `tests/security/test_headers.py` |
| **THREAT-05**: Открытый редирект (Open Redirect) | Подмена `redirect_uri` в запросе авторизации OIDC для перенаправления пользователя и кода на фишинговый ресурс. | 1. Строгая валидация `redirect_uri`: только точное совпадение со списком предварительно зарегистрированных URI клиента.<br>2. Запрещены wildcard (*), пути относительной адресации (`..`) и регулярные выражения. | `tests/oidc/test_redirect_uri.py` |
| **THREAT-06**: Повторное использование Authorization Code | Перехват authorization code и повторная попытка обмена на токены. | 1. Короткий TTL кода (60 секунд).<br>2. Атомарное погашение флага `is_used` в БД в транзакции.<br>3. Обязательная проверка PKCE (RFC 7636) с методом `S256`. | `tests/oidc/test_code_replay.py` |
| **THREAT-07**: Повторное использование Refresh Token (Token Replay) | Утечка refresh token и попытка параллельного использования атакующим и легитимным клиентом. | 1. Ротация refresh token при каждом использовании.<br>2. Отслеживание семейств токенов (`family_id`).<br>3. При обнаружении попытки использования уже отозванного токена все токены семьи аннулируются. | `tests/oidc/test_refresh_rotation.py` |
| **THREAT-08**: Эскалация привилегий и IDOR | Попытка обычного пользователя изменить чужой профиль, пароль или получить права администратора. | 1. Серверный RBAC с проверкой прав на каждом эндпоинте.<br>2. Self-service API жестко ограничены полями текущего пользователя из сессии (`session.user_id`).<br>3. Запрет изменения `is_superuser` или ролей через пользовательские эндпоинты. | `tests/security/test_rbac_idor.py` |
| **THREAT-09**: Компрометация соседнего поддомена `*.alxprgs.tech` | Злоумышленник захватил поддомен (например, `blog.alxprgs.tech`) и пытается перехватить cookie или обойти CORS. | 1. Сессионные cookies не используют wildcard domain `.alxprgs.tech`. Только точный host `auth.alxprgs.tech`.<br>2. CORS allowlist настроен строго на разрешенные клиентские origins. | `tests/security/test_subdomain_isolation.py` |
| **THREAT-10**: Утечки секретов и учетных данных в логи | Попадание паролей, токенов, ключей WebAuthn или кодов восстановления в журналы сервера. | 1. Централизованный фильтр логгирования маскирует чувствительные поля (`password`, `client_secret`, `token`, `totp_secret`, `recovery_code`).<br>2. В аудит пишутся только метаданные (тип события, user_id, ip, timestamp, user-agent). | `tests/security/test_audit_logging.py` |
| **THREAT-11**: Несанкционированный обход MFA (MFA Bypass) | Попытка обратиться к ресурсам без прохождения второго фактора при включённой политике MFA. | 1. Двухфазная аутентификация: при требовании MFA создаётся временный токен шага MFA с коротким TTL (5 минут), полноценная сессия не выпускается до успешного подтверждения фактора.<br>2. При отключении фактора на сервере не допускается автоматический вход ранее привязанных пользователей без административного сброса. | `tests/mfa/test_mfa_bypass.py` |

---

## 3. Политики и параметры криптографии

### 3.1. Хеширование паролей (Argon2id)
- Используется библиотека `argon2-cffi`.
- Параметры в соответствии с рекомендациями OWASP / RFC 9106:
  - `memory_cost`: 65536 KiB (64 MiB).
  - `time_cost`: 3 итерации.
  - `parallelism`: 4 потока.
  - `salt_len`: 16 байт.
  - `hash_len`: 32 байта.
- Ограничение длины пароля: минимум 8 символов, максимум 128 символов (защита от DoS-атак на хеширование длинных строк).

### 3.2. Асимметричная подпись OIDC токенов
- Алгоритм: `RS256` (RSA 2048-bit) с использованием `cryptography`.
- Поддерживается публичный набор ключей JWKS по адресу `/.well-known/jwks.json`.
- Каждый ключ снабжен уникальным идентификатором `kid`.
- Процедура плановой ротации ключей предусматривает период перекрытия (двойная публикация в JWKS) не менее времени жизни максимального access/id токена.

### 3.3. Шифрование секретов TOTP
- Секретные ключи TOTP пользователей шифруются алгоритмом AES-128-CBC / HMAC-SHA256 (спецификация Fernet).
- Ключ шифрования `TOTP_ENCRYPTION_KEY` передаётся через защищённую переменную окружения и никогда не коммитится в репозиторий.

---

## 4. Политика изоляции и отключения отложенных возможностей (Fail-Closed)

В соответствии с требованиями GOAL.md и AGENTS.md:
1. `FEATURE_TOTP_ENABLED = false`
2. `FEATURE_PASSKEY_ENABLED = false`
3. `FEATURE_RECOVERY_CODES_ENABLED = false`
4. `FEATURE_EMAIL_VERIFICATION_ENABLED = false`
5. `REQUIRE_VERIFIED_EMAIL = false`

Все флаги валидируются при запуске сервера:
- Если `FEATURE_TOTP_ENABLED = false`, то `FEATURE_RECOVERY_CODES_ENABLED` не может быть установлен в `true` (восстановление кодами допустимо только в связке с TOTP).
- Если `FEATURE_EMAIL_VERIFICATION_ENABLED = false`, то `REQUIRE_VERIFIED_EMAIL` не может быть установлен в `true` (нельзя требовать подтвержденную почту при отключенном механизме подтверждения).
- При `false` любые HTTP-запросы к эндпоинтам отключённого функционала немедленно возвращают ответ `404 Not Found` со стандартным телом ошибки:
```json
{
  "error": "feature_disabled",
  "detail": "Requested feature is disabled by server configuration"
}
```

## Sentry privacy boundary

Allowlist-проекция удаляет request bodies/headers/cookies/query, user/IP/geo, arbitrary extras, exception values всей цепочки, SQL и mail content; SDK data collection явно выключена. Envelope headers также ограничены. Incoming baggage очищается до SDK, outgoing tracing headers не уходят Google/SES. SQL parameters скрыты и в локальных SQL errors/logs. Expected 4xx не становятся Issues. Replay показывает только безопасную оболочку staging; исходный token URL запрещает recorder, transport отвергает recording без worker sanitizer. Production recorder hard-off. Direct ingestion раскрывает сетевой IP Sentry; запрет хранения IP/geo и server-side scrubbing необходимо проверить в проектах до rollout. Credentials не входят в artifacts/containers; подробности: [observability.md](observability.md).
