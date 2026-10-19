# Открытые дефекты и ограничения

[Историческая версия](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/testing/defects.md) содержит закрытые BUG-001…BUG-022, воспроизведение и прежние regression references. Их удаление из текущего реестра не означает новый PASS; постоянные тесты сохранены. Текущие контракты — [API](../api.md), порядок проверок — [методика](../03-test-procedure.md).

## DOC-REFRESH-01


Дата: 2026-10-06T18:49:38.497658+03:00. Исторические Resolved/Fixed записи выше сохраняют прежние результаты; они не означают повторную проверку текущего SHA.

### DOC-DEF-01 — Версия lock-файла не обновляется командой подготовки версии

- Требование: VER-01..03, единая версия и сохранение lock-файлов. Серьёзность: Low; статус: Open.
- Источник: scripts/bump_version.py, sync_all_components/check_consistency; frontend/package-lock.json.
- Ожидается: одна команда согласует VERSION, manifests и version metadata корня npm lock.
- Фактически: script обновляет только VERSION/два pyproject/package.json/CHANGELOG; package-lock не включён в update/check. Сейчас значения 0.2.0 совпадают; ошибка проявляется при следующем bump. Это не утверждение о сбое npm ci.
- Воспроизведение: в отдельной временной копии вызвать sync_all_components(0.2.1) и проверить lock version/ packages[""].version. Рабочие manifests не менять.
- Следующий шаг: DOC-VERSION-LOCK-01 — согласовать lock metadata и проверку consistency, добавить regression на отдельной копии. Код в этой задаче не исправлялся.

### Ограничение формата prerelease

Bump script преобразует alpha/beta/general SemVer, но build_identity и release workflow принимают только stable/rc.N. Текущее руководство явно ограничивает поддерживаемый release-профиль. Расширение формата требует отдельного согласования, в этой задаче не выполняется.

Проверка DOC-DEF-01: 2026-10-06T18:50:36.439015+03:00 — sync_all_components(0.2.1) воспроизведён на временной копии в artifacts/docs-refresh; package.json=0.2.1, root/package lock version=0.2.0. VERSION рабочего дерева остался 0.2.0.
