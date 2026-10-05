# Официальный бренд ALXPRGS

Канонический источник — [репозиторий ALXPRGS assets](https://github.com/alxprgstech/assets/tree/9b0eec08898a2eb2a02a66d895055c6ec7d97051/public), той же организации, которой принадлежит SSO. Дата получения:05.10.2026. Commit:`9b0eec08898a2eb2a02a66d895055c6ec7d97051`. [Профиль организации](https://github.com/alxprgstech/.github/blob/main/profile/README.md) также использует официальный SVG. SHA-256 и размеры всех локальных файлов — `source-manifest.json`.

`logo.svg`, `logo-avatar-full.png` и `logo-avatar-icon.png` скопированы без изменения исходных bytes. Полный SVG используется на desktop auth; PNG full — apple-touch-icon, PNG icon — favicon fallback. Это локальные URLs, без runtime зависимости от доступности внешнего assets сервиса.

`logo-mark.svg` — компактный vector viewport канонического SVG: исходные defs/градиенты и первые шесть icon paths с теми же coordinates/fills. Wordmark paths исключены, viewBox ограничивает только область mark. Геометрия и цвета не перерисованы. Размер около2.4kB вместо311kB PNG; используется в mobile auth, compact navbar, infrastructure core и modern SVG favicon. В публичной странице assets сам SVG уже используется для brand header; PNG avatar подтверждает роль отдельного mark.

Темы не перекрашивают artwork. Светлая backing surface сохраняет читаемость исходного navy wordmark и промежутков mark в Dark/Light. Функциональные иконки принадлежат Lucide; бренд ему не подменяется. Авторизационная SVG-схема не является источником доверия для OIDC.

Browser regression проверяет реальные локальные response bytes по manifest, loaded image/currentSrc на desktop/mobile в обеих темах, отсутствие внешних image requests, SVG favicon и navigation hit target. SVG проверен на отсутствие script/foreignObject/image/external href/event handler/DOCTYPE/entities; CSP не менялась.

`.gitattributes` отключает преобразование строк только для локальных брендовых SVG: Git сохраняет manifest bytes одинаковыми в Windows/Linux checkout. Для derived mark сохраняется его исходная сериализация; строгие browser size/SHA-256 assertions не нормализуют и не подменяют проверяемый файл.
