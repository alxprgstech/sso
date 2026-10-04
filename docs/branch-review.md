# Обзор веток и подготовка PR

BRANCH-PR-01, Codex, 04.10.2026. Inventory после `git fetch --all --prune`, `git ls-remote --heads origin`, ancestry checks и GitHub REST pagination всех branches/PR.

| Локальная ветка | Проверенный tip | Отношение к origin/main | Действие |
| --- | --- | --- | --- |
| `main` | `7e857ab` | Совпадает | PR не нужен |
| `new/production-readiness-audit` | `7e857ab` | Совпадает | PR не нужен; материалы включены в remediation |
| `new/production-readiness-remediation` | `17b444f` до текущего docs-only учёта | Два новых commits `ae700d7` и `17b444f` | Единственный необходимый новый PR в main, подготовлен |
| `new/skip-ses-without-credentials` | `dcc86d2` | Полностью входит в main | PR не нужен; [PR4 merged](https://github.com/alxprgstech/sso/pull/4) |
| `codex/ci-repair-pr9` | `ff3e5e7` | Полностью входит в main; remote ветка удалена ранее | PR не нужен; [PR1 merged](https://github.com/alxprgstech/sso/pull/1), новая codex-ветка не создаётся |

Все remote heads на момент inventory: `main` и `new/skip-ses-without-credentials`, их SHA совпадают с локальными. Open PR отсутствуют. [PR2](https://github.com/alxprgstech/sso/pull/2) merged; [PR3](https://github.com/alxprgstech/sso/pull/3) closed без merge, заменён PR4. Ветки/refs не удалялись, force/rebase/merge не выполнялись.

Для `new/production-readiness-remediation → main` подготовлены описание, migration указания, source SHA и реальные local test results, внешние E01…E07. [Карта исправлений](REMEDIATION_SUMMARY.md), [подробный аудит](PRODUCTION_READINESS_AUDIT.md). Detector self-test137 candidates/0new и Git whitespace PASS; private captures/keys/.env не включаются. Текущие дополнительные commits изменяют только учёт документов, не проверенный implementation SHA.

**История первоначального блокера:** GitHub API подтверждает `private=false`. Автоматическая проверка разрешений отклонила объединённую команду local commit + push (она не исполнялась), потребовав явного согласия на передачу закрытого source/docs в публичный repo. Правило AGENTS запрещает такую публикацию без поручения владельца; требуется уточнение именно публичного доступа. На момент отказа PR не создан, push не выполнен. Владельцу предложены разрешение публичного push/PR или самостоятельный перевод repo в private. Visibility в этой сессии не менялась.

Разрешение получено 2026-10-04T14:56:19.108344+03:00: владелец прямо ответил «Да, разрешаю push и PR в публичном репозитории». Блокер снят, public visibility не меняется.

Следующий шаг: повторить visibility/open-PR/main inventory, при необходимости push checked branch без force, создать только один PR и привязать к чату; проверить remote SHA/base/head/mergeability и CI state. Merge остаётся владельцу после review; замечания/конфликты исправляются в этой же ветке без ослабления защиты. Зелёный remote CI пока не заявлен.
