# CodeScene: два сохранённых контракта

Задача PR5-CI-01. Эти два замечания присутствовали на44c3ff9; проверка после
рефакторинга остальных рабочих файлов ещё выполняется. Гейт остаётся обязательным:
его исключения, thresholds и настройки не менялись.

| Файл / замечание | Причина сохранения | Доказательство |
| --- | --- | --- |
| docs/audit/readiness_probes_baseline.py — Complex Method / Overall Code Complexity | Это исторический исходный audit snapshot; менять его для текущей метрики значит менять исходное доказательство. Актуальные отрицательные проверки находятся в обязательных tests/, архив не заменяет их | SHA25639deb9b475ef5c9b9cbfa4edf33e77ed97ffd8b74c04fdd29fe9c57cbe16e7be; [карта постоянных критериев](../audit/readiness-probe-map.md); оба архива сравниваются с историческим содержимым |
| backend/app/migration_metadata.py include_object — Excess Number of Function Arguments | Framework вызывает callback с object, name, type_, reflected, compare_to. Переименование или упаковка аргументов только ради метрики скрывает этот контракт | [Официальный контракт Alembic](https://alembic.sqlalchemy.org/en/latest/api/runtime.html#alembic.runtime.environment.EnvironmentContext.configure.params.include_object); tests/test_migration_metadata.py проверяет все5 positional/named arguments и точную внешнюю marker boundary; actual PostgreSQL drift/upgrade проходят |

Решение, необходимое от владельца при сохранении только этих замечаний:
согласовать их рассмотрение как исторического evidence и framework contract
в политике CodeScene, либо сохранить failed gate для отдельного review.
Это не разрешение менять глобальные пороги, исключать рабочие файлы, отключать
обязательные тесты или ослаблять assertions/защиту. Такой policy exception здесь
не применён; successful Actions не объявляются успешным CodeScene.
