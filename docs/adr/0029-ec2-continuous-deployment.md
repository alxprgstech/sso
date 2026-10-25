# ADR-0029: EC2 и обновление main после CI

Дата: 25.10.2026. Статус: принято владельцем в интервью Spec Freeze v1; DEPLOY-EC2-01.

## Решение

Владелец разрешил активный CD после каждого push в main при успешном обязательном CI того же SHA.
Это заменяет прежний запрет CD-01; исторический полностью закомментированный шаблон сохраняется.
Production: пустой Ubuntu26.04 amd64 EC2 2vCPU/2GB/80GB; DNS-only auth.alxprgs.tech;
хостовый nginx/Let’s Encrypt, приложение/PostgreSQL в Compose. Установку выполняет владелец.

Один TLS gateway обслуживает static frontend и API через 127.0.0.1:8000, перезаписывая forwarding
headers; backend доверяет только gateway выделенной Docker-сети. Контейнер frontend нужен лишь
при сборке. Сохраняются отдельные DB owner/migrator/runtime, nonroot/read-only backend.

Runner собирает exact-SHA images и private transport с manifest/image ID/checksums. Registry,
release publication и сборка на EC2 не нужны. workflow_run ограничен successful same-repo main push;
два freshness check и server highwater/lock исключают откат запоздавшим запуском. SSH host key проверяется.

Секреты генерируются один раз на EC2. Runtime получает отдельный app.env без owner/migrator паролей.
Resend используется для регистрации и служебных уведомлений. Открытая регистрация выбирается
в интерактивном bootstrap администратора, mandatory email и три MFA default-off сохраняются.

Во время update writers остановлены, создан backup, затем migration/readiness/HTTPS.
После попытки миграции автоматический rollback только при идентичном migration fingerprint
и точном actual schema guard; иначе fail-closed maintenance. DB restore всегда ручной со свежим
deletion journal. Копии локальные, 30дней; renewal/backup failures через Resend, без логов в письме.

## Альтернативы и последствия

- Два nginx с пробросом схемы/IP: лишняя граница доверия; выбран прямой gateway.
- Сборка на 2GB EC2: дополнительное давление на память; выбран runner + SSH archive.
- Registry/release-only/CD-off: не соответствуют выбранному владельцем push-main сценарию.
- Автоматическое восстановление DB: риск потери записей/возвращения удалённых субъектов; отклонено.
- Внешние backup, SSM, HA и изменение сетевых правил исключены владельцем из текущего объёма.

Деплой-ключ фактически привилегированный, несмотря на ограниченный sudo command. Потеря EC2
уничтожает локальные backup; владелец сохраняет секреты отдельно. Код не доказывает live-приёмку.
Оператор bootstrap обновляется вручную проверенным установщиком; приложение — автоматически.

Уточнение владельца 25.10.2026: разрешён ручной workflow_dispatch только main без успешного общего CI. Автоматический gate, exact SHA/freshness и обязательный transport test сохранены; CI ошибки не маскируются.
