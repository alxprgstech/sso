# ADR-0025: ограниченный объём anonymous denied audit

Дата: 20.10.2026. Статус: принято для SSO-SEC-0004 (#18).

Retention90дней уже работал; он не ограничивал частоту INSERT. Каждый анонимный401/403/429 создавал отдельную задачу/сессию/строку action_denied.

Анонимные отказы считаются в process-local bounded buffer по серверному route name/status до создания фоновой задачи или DB-сессии. Максимум256 обычных комбинаций плюс3 overflow counters; нет ключей IP/username/URL/query/cookie. Счётчик насыщается на2^63−1. Каждый worker сбрасывает непустые counters одной транзакцией раз в60с; graceful shutdown делает финальный flush. Ошибка/отмена сохраняет bounded counters для следующей попытки, включая ошибки rollback. Одновременные flush одного процесса исключены.

Audit event сохраняет route/reason/count/aggregated/window_seconds, без выдуманной привязки к одному request_id или субъекту. Максимум259 aggregate rows за штатный60-секундный tick на worker плюс финальный shutdown. Снимок и новые counters ограничены отдельно; при overflow причина/status и общее число сохраняются, детализация маршрута теряется. Это бюджет по worker, не глобальный распределённый cap; число workers задаётся оператором.

Authenticated denied actions и предметные login_failed/security mutation audit остаются индивидуальными; их существующие auth/source quotas не отключены. Retention90дней не меняется. Crash/kill может потерять последний несохранённый anonymous интервал; долговечность предметных транзакционных событий не меняется. window_seconds — период штатного flush, при outage counts могут включать несколько периодов.

Альтернативы: per-IP sampling допускает cardinality/flood; DB-upsert на каждый запрос оставляет IO-amplification; durable внешняя очередь требует невыбранной инфраструктуры. Отказ от всех anonymous событий потерял бы счётчики. Нагрузочные показатели не выдумываются; проверяются малые серии, bounded state, failures и authenticated regression.
