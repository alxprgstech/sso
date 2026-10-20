# ADR-0026: регистрация требует mailbox и исходный browser proof

Дата: 20.10.2026. Статус: принято в рамках SSO-SEC-0005 (#19).

Повторный start по одному email менял credentials в pending, и жертва могла подтвердить их письмом. Сохранение первой заявки переносит атаку в attacker-first порядок; новая UUID сама по себе не защищает от перехода по новой подменённой ссылке.

Каждый start создаёт независимый32-byte browser secret в host-only HttpOnly SameSite=Lax cookie (Secure/__Host- при HTTPS/production; один активный flow на браузер). В pending хранится только SHA-256. Повторный start вращает browser proof вместе с mail secrets и credentials, под прежним transaction advisory/row lock. Все confirm способы и resend требуют соответствующий browser proof; браузер старой заявки не может создать аккаунт из нового письма. Wrong-browser отказ не расходует code attempts и не изменяет pending. Code/link/action остаются атомарно одноразовыми. Origin/Referer policy применяется ко всем cookie-bearing enrollment mutations.

Миграция0014 добавляет nullable browser_secret_hash без реконструкции секретов. Legacy pending не может быть подтверждён или resend: начать регистрацию заново. Активные пользователи/сессии не затрагиваются. TTL mailbox10мин, cookie1час, send/code quotas прежние. Resend не продлевает cookie или меняет credentials. Код с другого устройства можно ввести в исходной форме; ссылка открывается в исходном браузере.

Gmail shortcut сохранён как browser GoTo/ViewAction, ведущий на обычную verification page с явным подтверждением. [Официальный Gmail Go-to action](https://developers.google.com/workspace/gmail/markup/reference/go-to-action) поддерживает такой переход. Он заменяет server-to-server ConfirmAction из ADR0023: Google server не имеет browser proof. Старый confirm-gmail endpoint сохраняет Google signature, action secret и replay проверки, но также требует browser proof и поэтому не принимает автономный Google request. Не рекламируется заведомо неработающий server action. Live Gmail rendering/sender registration отдельно не проверялись.

Изначальная идея «Gmail подтверждает mailbox, затем владелец flow завершает в browser» отвергнута до тестового кандидата: атакующий владеет своим flow и мог бы завершить его после клика жертвы. Не выпускаем такой промежуточный completion grant. Альтернатива полноценного password-after-email enrollment меняет весь onboarding и не требуется для разделения двух доказательств.

Остаток: повторная заявка может мешать доступности pending, ограниченной прежними квотами; это не даёт takeover без обоих proofs. Один браузер хранит один enrollment flow. Администраторский и legacy login не получают нового требования.
