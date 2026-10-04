# ADR-0015 — Security revision и чувствительная повторная аутентификация

Дата: 04.10.2026; принято для AUDIT-FIX-02 (F-02…F-06), реализация in_progress.

User.security_revision увеличивается при смене/сбросе пароля, блокировке/разблокировке,
изменении прав, адреса и подтверждённых факторов. Browser sessions, authorization codes,
refresh grants, MFA-step и sensitive proofs несут snapshot. Все операции выпуска/отзыва
сериализуются PostgreSQL row lock User **до** session/grant/factor/challenge rows.
Reset, обмен code, refresh и завершение MFA не могут оставить живой grant старой revision:
если выпуск выиграл гонку, последующий reset отзывает его; если reset первый — snapshot
отвергается. Offline access JWT у RP сохраняет штатное окно до TTL; мгновенный внешний
отзыв не заявляется. Серверные endpoints дополнительно проверяют текущую revision/политику.

Чисто stateless MFA-step отвергнут: он переживает security events и допускает повторный выпуск
сессии. Криптографический step содержит revision/jti/audience/type и связан с hashed one-use
DB record. Factor verification, consumption шага и выпуск сессии завершают одну транзакцию.
API не продлевает auth_time; он фиксируется только фактической аутентификацией.

Recent reauth proof связывается с user/session/action/revision, коротким TTL и атомарным
погашением. Текущий password плюс настроенный допустимый MFA требуются до выдачи proof.
Default-off не снимает требования уже настроенного фактора. Enrolment replacement хранится
отдельно от действующего TOTP и не отключает его до подтверждения нового секрета.

Email policy централизована на всех путях обычного доступа. Pending email-change challenge
не меняет действующий адрес; подтверждение делает смену и verified flag атомарно, под User
lock с проверкой revision. Admin change очищает verification и старые challenges.

Password/account/source/MFA-challenge/client quotas используют существующую PostgreSQL
privacy_rate_windows с отдельными namespaces и независимым commit до дорогостоящей проверки;
сбой БД даёт отказ. Bounded Argon2 work выполняется вне event loop. Альтернатива только
процессных counters не покрывает multiple workers; Redis не требуется текущему продукту.

Точные API/action names, ограничения и фактические PG/browser результаты обновляются
в документации по завершению сценариев. ADR сам по себе не закрывает ни одну находку.
