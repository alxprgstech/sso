# ADR-0010 — Sentry: минимизация данных и неизменяемая сборка

> Сверка 06.10.2026: сохранено решение на дату принятия; это не новый результат приёмки. Действующий профиль: [архитектура](../architecture.md), [API](../api.md), [статус](../status.md).

Дата: 02.10.2026. Статус: принято владельцем в задании на реализацию.

## Решение

Два проекта в организации Sentry DE: backend и frontend. Прямая браузерная отправка, общий release `alxprgs-sso@VERSION+SHA`, transaction/static mode. Ошибки отделены от security audit и stdout. SDK выключены по умолчанию и не являются зависимостью доступности SSO. Обычные тесты используют только локальные transports.

Данные событий формируются разрешающей проекцией. Bodies, headers, cookies, query, пользовательские данные, locals, SQL и тексты всей цепочки исключений не отправляются. Replay разрешён только в staging: маскирование и полная блокировка чувствительных страниц, отдельный chunk и локальный worker. Production hard-off имеет приоритет над rates.

Frontend получает публичную конфигурацию без БД с пределом ожидания 300 ms. Build identity неизменяема. Debug IDs внедряются при единственной сборке; private maps сохраняются отдельно, удаляются из deploy artifacts и загружаются только доверенным release шагом. Upload token недоступен build/test и контейнерам. CD остаётся закомментированным.

## Причины и альтернативы

Полный сбор с последующим regex scrubbing недостаточен для SSO: значения встречаются в URL, exception chains, DOM и SQL. Поэтому выбран allowlist. Tunnel/Relay увеличили бы объём эксплуатации; владелец выбрал direct ingestion, понимая раскрытие сетевого IP ingestion сервису. Router, очереди и telemetry service не нужны для существующего приложения. Streamed spans осложняют полную очистку transactions и расчёт Student quota; выбран static mode.

## Проверка и границы

Настоящие SDK envelopes, canary secrets, PostgreSQL с safety marker, serialized Replay, outage/disabled/duplicate/propagation regression tests и проверка архивов. Live source-map association, privacy audit, организация, квоты и staging overhead требуют внешнего стенда; локальные проверки их не заменяют. Все flags остаются false до приёмки соответствующего канала.

## Уточнения при реализации 02.10.2026

EU storage и оба проекта подтверждены владельцем; public DSN сохранены в игнорируемом .env, ingestion выключен. rrweb Meta в SDK 11.2 проходит мимо public recording hook, а отсутствие Worker допускает SDK fallback без compression. Поэтому initial query/fragment запрещает старт Replay; закреплённый локальный worker строит allowlist recording, а финальный transport требует очищенный compressed recording. Неудача отключает только Replay envelope. Альтернатива — собственный recorder/Relay — потребовала бы новой архитектуры; выбран ограниченный SDK wrapper с обязательным browser regression при upgrade. Replay оставляет только оболочку, геометрию и навигацию, без произвольных DOM attributes/CSS.

У Vite 8 final entry-map serialization удаляет plugin metadata. После injection восстанавливается только Debug ID из того же JS; mappings/code не изменяются. Integrity gate сравнивает maps, JS, hashes и identity внутри wheel/archive. Tagged upload требует clean source metadata; dirty локальная сборка допустима только для offline проверки. Baggage очищается внешним FastAPI __call__ до patched Starlette integration, а не внутренним middleware после неё.
