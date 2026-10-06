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

Владелец прямо разрешил эти два исключения 04.10.2026.
Это не разрешение менять глобальные пороги, исключать рабочие файлы, отключать
обязательные тесты или ослаблять assertions/защиту. Результат нового remote анализа проверяется отдельно; successful Actions не объявляются успешным CodeScene.


## Реализация исключений — 2026-10-04T22:04:29.217583+03:00

`.codescene/code-health-rules.json` содержит единственный точный путь архива и только Complex Method / Excess Number of Function Arguments с weight0.0. Архив остаётся byte-exact; другие его правила и все рабочие тесты сохраняются. Никаких glob-масок, thresholds и disable-all нет.

Непосредственно над `include_object` добавлен `@codescene(disable:"Excess Number of Function Arguments")`: он действует только на эту функцию. Сигнатура из пяти аргументов и тело неизменны; другие функции и правила этого модуля не исключены. Причина записана рядом с директивой.

Способ соответствует [официальной документации CodeScene](https://codescene.io/docs/guides/technical/code-health.html#adapt-code-health-to-your-coding-standards). UI недоступен без GitHub sign-in; настройки version-controlled, вход и глобальная конфигурация не менялись. Новый обязательный CI и CodeScene ещё pending.


Уточнение 2026-10-04T23:24:44.165802+03:00: CodeScene7806460 подтвердил локальную callback directive и архивный ComplexMethod override. Второе фактическое архивное замечание — Excess Number of Function Arguments у test_authorize_honors_prompt. Неиспользуемое OverallCodeComplexity имя заменено только в том же exactpath rule-set; ранее название было ошибочно выведено из сводного числа2rules. Новыйremoteанализ pending.


## Проверенный результат — 2026-10-04T23:31:35.029980+03:00

На `94298ed4cfd05362b08b9b5d778013346554c06c` все **9 обязательных [Actions jobs](https://github.com/alxprgstech/sso/actions/runs/37232030605) успешны**; [CodeScene7806490](https://codescene.io/projects/85555/delta/results/7806490) — success, все3qualitygates прошли. ДваSESjobs skipped поCI03 безAWS; реальнаядоставка не проверена. Настройки подтверждены настоящим анализомPR; все3gates/profile сохранены. Архивнаяpolicy содержит только2фактическихrule names, callbackdirective одна. Последующийdocs-onlyhead не меняетpolicy/runtime/tests и проверяетсяотдельно.

## Актуальная трактовка

Указанные success/pending относятся к своим историческим SHA и моментам. Два разрешённых исключения сохраняют точные paths/rules; DOC-REFRESH-01 не менял CodeScene policy и не запускал удалённый анализ. Текущий статус нового SHA нужно подтвердить отдельным прогоном, а не записью документа.
