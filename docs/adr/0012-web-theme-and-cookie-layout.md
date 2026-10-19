# ADR-0012: тема и нижний баннер cookies

Принято 03.10.2026; layout и presentation foundation частично заменены [ADR-0013](0013-pr-quality-refactoring.md) и [ADR-0021](0021-frontend-design-platform.md).

Исходное решение использовало общую palette/theme для SPA и demo, fixed banner и ResizeObserver reserve. Resize race сделал последнее ненадёжным: ADR-0013 заменил reserve нижней строкой CSS flex-shell. ADR-0021 выделил SPA tokens/Tailwind и Dark default; demo сохранили прежнюю palette/System default. Подробности текущего layout — [frontend](../frontend.md).

Сохраняются System/light/dark, синхронный self-hosted bootstrap без CSP inline exception, локальный выбор без user identifier, cross-tab/no-storage поведение, независимость origins, keyboard/focus и privacy contracts. Выбор темы не является согласием на диагностику. Footer на коротких страницах прижат вниз растущим main, на длинных следует за содержимым; banner не перекрывает формы, QR сохраняет контрастную подложку.

Альтернативы React-only/inline bootstrap не покрывают demo либо ослабляют CSP; fixed без CSS layout/reserve перекрывает контент. [Историческая версия](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/adr/0012-web-theme-and-cookie-layout.md) сохраняет полную причину и последовательность замен.
