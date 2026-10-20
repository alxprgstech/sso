# ADR-0028: единый start-путь регистрации

Дата: 20.10.2026. Статус: принято для SSO-SEC-0003 (#17).

409/202 раскрывал membership. Ранний вариант с response-only UUID и Argon2 для коллизии убирал одиночный status oracle, но повторный start отличал свежий fake UUID от стабильного pending UUID; MAX_SENDS и SMTP failure также отличали пути. Этот вариант отменён до merge.

Все start-запросы проходят один реальный Argon2/pending/mail путь без User lookup. Коллизии username/email проверяются только после mailbox proof в confirm; User/credentials никогда не перезаписываются. Новая запись User появляется только при свободных identity и подтверждённой почте. Коллизия после proof возвращает409 без указания поля. Это предусмотренная повторным аудитом альтернатива «принимать заявку и разрешать коллизию только на confirm».

Сохранены source registration5/60с и email3/60с, process filter, MAX_SENDS3/час, attempts5, TTL10мин, unique DB constraints, legal consent и отсутствие автоматической session. Ввод новых лимитов или reset quota ради тестов не требуется. Resend неизвестной/исчерпанной заявки нейтрален202; для реальной заявки старые mail secrets инвалидируются как прежде. Provider failure503 одинаков для occupied/available identity; pending сохраняется. Владельцу занятого email может прийти письмо в пределах тех же ограничений, но оно не сбрасывает пароль и не выдаёт доступ.

Альтернативы: deterministic fake IDs не устраняют все state/quota/transport различия; отдельная decoy schema/outbox усложняет миграции и обработку секретов; BackgroundTasks не нужны при одном одинаковом delivery пути. Константное wall-clock время сети/БД не заявлено, но ветвление по существованию User до proof отсутствует. Mailbox owner может узнать о конфликте после proof — это намеренная граница доверия.

Отдельный SSO-SEC-0005/ADR0026 добавляет browser binding к pending; функциональная зависимость исправления status oracle от него отсутствует. При совместном merge сохранить оба требования и актуальные документы.
