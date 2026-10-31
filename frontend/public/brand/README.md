# Официальный бренд ALXPRGS

Канонический источник — [репозиторий ALXPRGS assets](https://github.com/alxprgstech/assets/tree/9b0eec08898a2eb2a02a66d895055c6ec7d97051/public), той же организации, которой принадлежит SSO. Дата получения:05.10.2026. Commit:`9b0eec08898a2eb2a02a66d895055c6ec7d97051`. [Профиль организации](https://github.com/alxprgstech/.github/blob/main/profile/README.md) также использует официальный SVG. SHA-256 и размеры всех локальных файлов — `source-manifest.json`.

`logo.svg`, `logo-avatar-full.png` и `logo-avatar-icon.png` скопированы без изменения исходных bytes. Полный SVG сохранён как канонический источник; PNG full — apple-touch-icon, PNG icon — favicon fallback. Это локальные URLs, без runtime зависимости от доступности внешнего assets сервиса.

`logo-mark.svg` — компактный vector viewport канонического SVG: исходные defs/градиенты и первые шесть icon paths с теми же coordinates/fills. Wordmark paths исключены, viewBox ограничивает только область mark. Геометрия и цвета не перерисованы. Размер около2.4kB вместо311kB PNG; используется в mobile auth, compact navbar, infrastructure core и modern SVG favicon. В публичной странице assets сам SVG уже используется для brand header; PNG avatar подтверждает роль отдельного mark.

`logo-adaptive.svg` используется через внешний SVG `<use>` на desktop auth: к корню канонического SVG добавлен `id="logo"`, только navy wordmark fill заменён на `currentColor`. Цвет наследуется от `--text-primary`: светлый в Dark и тёмный в Light, включая переключение темы без перезагрузки. Все пути, размеры и градиенты сохранены. Белой подложки нет ни у полной версии, ни у компактного знака; CSS-фильтры не используются. Функциональные иконки принадлежат Lucide; бренд ему не подменяется. Авторизационная SVG-схема не является источником доверия для OIDC.

Browser regression проверяет реальные локальные response bytes по manifest, SVG use и адаптивный цвет на desktop, loaded image/currentSrc на mobile в обеих темах, отсутствие внешних image requests, SVG favicon и navigation hit target. SVG проверен на отсутствие script/foreignObject/image/external href/event handler/DOCTYPE/entities; CSP не менялась.

`.gitattributes` отключает преобразование строк только для локальных брендовых SVG: Git сохраняет manifest bytes одинаковыми в Windows/Linux checkout. Для derived mark сохраняется его исходная сериализация; строгие browser size/SHA-256 assertions не нормализуют и не подменяют проверяемый файл.
