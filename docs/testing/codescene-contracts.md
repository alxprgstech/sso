# CodeScene: два сохранённых контракта

Задача PR5-CI-01, статус done: владелец разрешил два точечных исключения, remote gate прошёл. На source SHA
`f9e06d71c7806d71d9226cfb591585cbf5f3ef83` остались только эти два замечания CodeScene;
все 9 обязательных [Actions jobs](https://github.com/alxprgstech/sso/actions/runs/37225223182) прошли.
Все остальные причины failed checks исправлены и перепроверены. Гейт остаётся обязательным:
глобальные thresholds и другие правила не меняются.

| Файл / замечание | Причина сохранения | Доказательство |
| --- | --- | --- |
| docs/audit/readiness_probes_baseline.py — Complex Method / Excess Number of Function Arguments | Это исторический исходный audit snapshot; менять его для текущей метрики значит менять исходное доказательство. Актуальные отрицательные проверки находятся в обязательных tests/, архив не заменяет их | SHA-256: 39deb9b475ef5c9b9cbfa4edf33e77ed97ffd8b74c04fdd29fe9c57cbe16e7be; [карта постоянных критериев](../audit/readiness-probe-map.md); оба архива сравниваются с историческим содержимым |
| backend/app/migration_metadata.py include_object — Excess Number of Function Arguments | Framework вызывает callback с object, name, type_, reflected, compare_to. Переименование или упаковка аргументов только ради метрики скрывает этот контракт | [Официальный контракт Alembic](https://alembic.sqlalchemy.org/en/latest/api/runtime.html#alembic.runtime.environment.EnvironmentContext.configure.params.include_object); tests/test_migration_metadata.py проверяет все 5 positional/named arguments и точную внешнюю marker boundary; actual PostgreSQL drift/upgrade проходят |

Владелец разрешил эти два точечных исключения 04.10.2026. Они не разрешают менять глобальные пороги, исключать рабочие файлы или ослаблять тесты. Действующая конфигурация — `.codescene/code-health-rules.json` и локальная директива `include_object`.

Исторический итог: SHA `94298ed4cfd05362b08b9b5d778013346554c06c`, [Actions](https://github.com/alxprgstech/sso/actions/runs/37232030605) и [CodeScene](https://codescene.io/projects/85555/delta/results/7806490) успешны; два внешних SES job пропущены по согласованной CI policy. Это не результат нового SHA.

[Историческая версия](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/testing/codescene-contracts.md) содержит завершённую диагностику policy.
