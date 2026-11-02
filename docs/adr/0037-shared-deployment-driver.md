# ADR-0037: Общий deploy driver для MP и SSO

Дата: 03.11.2026. Статус: принято локально; DEPLOY-SHARED-01.

Дублирующиеся upload/workflow-команды расходились по ограничениям архива,
проверкам SHA-256 и итоговым статусам. Серверные операторы уже поставляются из ctl.

Общий `deploy/ec2/deploy.py` вендорится из `alxprgstech/.github` вместе с
`upload.sh` и regression tests. `project.json` задаёт transport и команды
build/runtime/public checks проекта. Workflow сохраняет trigger, CI gate,
runner setup, приватное хранилище и зависимости jobs. Ожидаемый SHA-256 идёт
из outputs build; скачанный архив не является источником ожидаемого хеша.

У SSO сохранены inbox/scp, sudoers и строгий `ssoctl-result`; у MP — forced SSH
и потоковая передача. Общие ограничения: обычный файл без symlink, 1 байт–3 GiB,
проверка digest до verify и upload, повторная проверка main, временные SSH-файлы
с закрытыми правами, обязательный публичный результат. SSO public-check проверяет
также точный healthy backend/frontend SHA через `--require-installed`.

Альтернатива — единый монолит с общей Compose/build-схемой — смешала бы разные
образы, миграции и стенды. Reusable workflow по mutable main добавил бы сетевую
зависимость и риск рассогласования runner/storage. Копии с проверяемыми хешами
сохраняют воспроизводимость project commit; обновление выполняется явно через
`deploy/ec2/sync.py` в `.github` с проверкой `--check`.

`scripts/deploy_result.py` остаётся совместимым CLI к общему parser. Старый
оператор SSO без протокола помечается `deployed_legacy`, как прежде. Обновление
ctl отдельно; новые права на сервере не нужны. Локальные тесты не доказывают
работу Linux SSH/scp, GitHub scheduler или production; запуск CD не выполнялся.
