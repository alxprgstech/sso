# ADR-0014 — Production-конфигурация, ключи и SMTP TLS

Статус: принято для AUDIT-FIX-01; дата 04.10.2026, исполнитель Codex.

Production отклоняет неполную конфигурацию до импорта сервера: случайный SESSION_SECRET_KEY,
отдельный действительный Fernet ключ, постоянный RSA не менее 2048 bits, явный безопасный kid,
один точный HTTPS origin issuer/API/UI/WebAuthn, bounded TTL и DEBUG=false.
PEM допускается через secret mount или secret environment; пути/содержимое не включаются в ошибки.
Известные development значения отвергаются даже при выключенном TOTP.

RSA rotation выполняется через постоянный ключ и согласованный restart всех workers.
Предыдущий public key публикуется/принимается только до timezone-aware
JWT_PREVIOUS_KEY_VALID_UNTIL; процессная rotation разрешена только в dev/test.
Альтернатива — процессная генерация и rotation — отвергнута из-за несовпадения workers/restarts.
Период перекрытия выбирает оператор с учётом последнего выпуска/TTL/clock skew и logout hints;
после deadline старые подписи отвергаются, включая logout hints.

Сохраняются SMTP и SES. STARTTLS использует стандартный SSLContext с CERT_REQUIRED/hostname
и системным trust store; SMTP_CA_FILE расширяет доверие только явно выбранным CA.
Нет plaintext fallback, production SMTP требует TLS, credentials без TLS запрещены во всех профилях.
Альтернатива prod-only SES не выбрана: verified SMTP входит в существующий продукт.

Генератор записывает один тип ключа в новую private directory (POSIX 0700/0600;
Windows owner-only ACL до записи). Повторный destination отвергается. Session rotation
отличается от RSA, TOTP ciphertext migration выполняется отдельно в offline maintenance
и транзакции. Предварительный backup/restore и реальный PG drill обязательны до эксплуатации.

Основания: F-01/F-08/F-20, GOAL ARCH-06/SSO-05/06, запрет TLS bypass.
Источники: [Python SSL](https://docs.python.org/3/library/ssl.html#ssl.create_default_context),
[SMTP STARTTLS](https://docs.python.org/3/library/smtplib.html#smtplib.SMTP.starttls),
[MultiFernet rotation](https://cryptography.io/en/latest/fernet/#cryptography.fernet.MultiFernet.rotate).
Новые зависимости не добавлены; используемые версии сохраняет requirements-lock.txt.
