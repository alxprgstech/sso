# ADR-0027: source-scoped login quotas и конечный Argon2 admission

Дата: 20.10.2026. Статус: принято для SSO-SEC-0006 (#20).

Глобальные unauthenticated identifier/account5/60с позволяли постороннему заблокировать владельца. Четыре queued/running password jobs при двух workers давали немедленный503 на малом burst и влияли на password/reauth/clientsecret.

Сохраняем persistent PostgreSQL source30/60с; identifier+source и account+source получают5/60с до hash. Username/email одного аккаунта суммарно расходуют account/source квоту; JSON tuple исключает неоднозначность ключа. Все попытки, включая успешные, учитываются как раньше; новые namespaces отделяют старое global lockout окно. Source вычисляется только trusted-proxy policy, forged forwarding headers не меняют его. Ошибки БД остаются fail-closed503, JWT/MFA/email policy не меняются.

До Argon2 процесс допускает максимум16 queued+running и максимум2 на source. Исполняются по-прежнему только2 Argon2 jobs; параметры time3/memory65536KiB/parallelism4 не меняются. Очередь ограничивает краткий burst нескольких источников без роста числа workers/памяти Argon2. Один источник не занимает всю очередь; за NAT пользователи делят source budget. Saturation возвращает429 authentication_busy/Retry-After1, а не503; persistent window429 получает Retry-After60. Cancellation/disconnect не освобождает slot до фактического окончания worker; source map очищается при release. Internal CLI/service jobs без request context ограничены общим16, API всегда ставит source context и сбрасывает его в finally.

Это замена attacker-consumable global identity lock на source-scoped anti-brute-force+bounded CPU admission, а не обещание неограниченной доступности. Распределённый атакующий может иметь5попыток/account/source и требует edge/global bot admission; sourceNAT и distributed flood остаются эксплуатационными ограничениями. Нельзя гарантировать доступ fresh owner под произвольным распределённым flood без дополнительного доверенного фактора/challenge. Не добавляем MFA/captcha обходов и не увеличиваем Argon2 workers.

Альтернативы: оставить global hard lock сохраняет targetedDoS; проверить пароль перед account limit позволяет неограниченно проверять guesses; unbounded очередь допускает exhaustion; просто заменить503 на429 не сохраняет свободную ёмкость другому источнику; увеличить workers повышает память. Новые тесты используют реальные Argon2 checks и малый8requestburst с управляемыми scheduling gates, а не нагрузочный benchmark.
