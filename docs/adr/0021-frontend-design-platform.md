# ADR 0021 — frontend ALXPRGS Design Language v1

Дата: 2026-10-05. Статус: принято для FRONTEND-REDESIGN-01; основная реализация и локальные проверки выполнены; официальный artwork найден через GitHub organization API и включён локально; итоговая browser проверка46default/10enabled и прежняя scoped brand2 и visual inspection прошла.

## Решение

Сохранить React18 и защищённый API-клиент. Tailwind4.3.3 подключить официальным Vite plugin той же версии (peer Vite5–8). React Router7.18.4 — последняя registry-версия7 с React>=18; текущая8.4.0 требует React>=19.2.7, такое обновление не относится к цели. Декларативные Routes размещаются после единого server-state gate. Backend остаётся authority для session purpose, legal/deletion/MFA/RBAC.

Radix Dialog/DropdownMenu/Tooltip — MIT, focus/keyboard/modal semantics. Компоненты принадлежат source проекта, без shadcn generator/default theme. Native select/checkbox/radio сохраняют браузерную семантику. cmdk1.1.1 (MIT, React18/19) — command palette внутри нашего Dialog. Motion14 (MIT, React18/19) — contextual transitions, reducedMotion=user плюс отключение decorative/height travel. Lucide1.52 (ISC, React18) — named imports. Geist1.7.2 (OFL) — локальные variable WOFF2, без runtime CDN.

Версии/peer/license проверены через официальный npm registry05.10.2026; установка/audit298packages:0vulnerabilities. Источники: [Tailwind/Vite](https://tailwindcss.com/docs/installation/using-vite), [theme](https://tailwindcss.com/docs/theme), [React Router](https://reactrouter.com/start/declarative/installation), [Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog), [Motion](https://motion.dev/docs/react-installation), [reduced motion](https://motion.dev/docs/react-motion-config), [Lucide](https://lucide.dev/guide/react), [Geist](https://github.com/vercel/geist-font).

## Альтернативы

CSS patches не устраняют отсутствующие utilities и две системы дизайна. Полная замена auth scenarios опасна потерей bindings; переносится представление при сохранении проверенных вызовов/сериализации. React upgrade добавляет необязательный риск. Собственный focus trap проигрывает Radix по поддержке. CSS tokens первичны для обеих тем; Tailwind генерирует semantic utilities.

## Инварианты и проверка

Public legal/email доступны; password_change выше force_login; deletion выше legal; unknown routes получают404; admin gate не заменяет backend RBAC. Query branding не используется. Без trusted metadata RP context не выдумывается. safe return_to, CSRF, request digest/retry-once, proof action/user/session/payload, email explicit confirmation, default-off сохраняются. Portal content явно data-sentry-block/sso-sensitive. Route names добавляются только в finite privacy allowlist, без query/IDs.

Baseline:28component testsPASS; buildPASS, CSS12.05kB/entry JS568.67kB(gzip174.63), warning>500kB. Это исходные результаты. Проверять incremental types/lint/components/build, затем real browser/PG/security/CSP/visual/размеры. Official brand отсутствует в repository: уточнение владельцу, не рисовать замену.

## Уточнение RP context (05.10.2026)

В существующем API отсутствует trusted display metadata для входа из OIDC-клиента. Добавлен GET /oauth/client-context с client_id/redirect_uri: общий limiter и rejection duplicates, существующие active-client и exact redirect validators, no-store, только name/origin. Endpoint не создаёт session/code/grant и не заменяет /authorize; query client_name/logo не используются. Альтернатива — показывать сырые query branding — отвергнута; полная consent subsystem вне цели. Настоящая PG regression включает no-cookie/no-grant и mismatch/duplicate/inactive/unknown. Неиспользуемый Radix Tabs удалён; разделы — реальные NavLinks/history.

## CSP, accessibility и современный Passkey UX

Настоящий Nginx Chromium выявил inline style tag из react-remove-scroll при Radix Overlay, запрещённый существующим style-src. CSP не расширяется. Используется Radix modal Content (FocusScope/DismissableLayer/aria isolation), собственный статический overlay, CSS scroll lock и небольшой проверяемый стек `inert` для background/parent dialogs. Escape blocked только во время mutations; busy сохраняет focus, остальные dialog возвращают focus инициатору. DropdownMenu — обычный non-modal popup с Radix keyboard/focus. Исходный ручной focus trap удалён. Axe4.13 (MPL2.0) dev-only проверяет WCAG2A/AA/2.1AA/best-practice без отключений правил; Prettier3.9.9 (MIT) — dev-only для читаемых source-owned views/controllers.

Проверены [W3C WebAuthn3 conditional mediation](https://www.w3.org/TR/webauthn-3/#sctn-getAssertion) и [браузерное form autofill](https://web.dev/articles/passkey-form-autofill)05.10.2026. Текущий сервер уже поддерживает discoverable sign-in: без username allowCredentials отсутствует; registration residentKey=preferred, UV=required. Явная заметная кнопка запускает эту церемонию. Non-discoverable credential использует введённый username. Conditional autofill требует capability detection, `username webauthn`, AbortController и жизненного цикла незавершённого запроса: браузер может ждать неограниченно, серверный challenge живёт5min. В этой миграции не вводится автоматическая выдача/обновление challenges на просмотре страницы и гонка с password/MFA/explicit credential ceremonies. Conditional-only UX не подходит всем прежним credentials (resident preferred не гарантирует discoverable). Это инженерное решение сохранить explicit flow после исследования, а не утверждение о запрете conditional протоколом; будущая реализация может добавить ограниченный lifecycle с отдельным покрытием истечения/отмены/параллельных ceremonies. Origin/RP ID/UV/challenge/signature остаются точными, verifier fallback отсутствует.

Dark — default только SSO; явно выбранный System и cross-tab preferences сохраняются, demo сохраняют прежний default System. Sidebar240px, auth440px, control44px/touch44px, admin fine-pointer rows48px/buttons36px. AA требует отдельных text-tertiary/control-border оттенков поверх нормативных surface цветов; это осмысленная адаптация tokens. Fonts bundled local и license включается в static artifact.


Итоговая проверка решения: настоящая enforcing CSP/default43/finalUI33/enabled10, component36/unit13, fullPG625/16subtests, keyboard/Axe/visual и Sentry harness9 PASS. Callback-ref/useLayoutEffect регистрирует inert stack после появления Radix portal; positive nested focus/inert browser regression пройден. Числа относятся к рабочему diff, не опубликованному release; подробности/история отказов — в implementation report.


Дополнение официального бренда: источник assets найден через read-only GitHub organization API после недоступности domain/web-profile. Совпадает владелец SSO и assets — alxprgstech. Pinned commit9b0eec08898a2eb2a02a66d895055c6ec7d97051; fullSVG/avatars byte-exact, compact SVG содержит исходные6paths/defs и только role viewport. Светлая backing сохраняет navy artwork в обеих темах. Это снимает первоначальный input blocker; [provenance](../../frontend/public/brand/README.md). Никаких runtime external images или CSP изменений. Default45/enabled10/brand2 и real loaded image/hash проверки PASS.

Дополнение устойчивости: отрицательный browser regression доказал, что failed Infrastructure chunk попадал в общий boundary и убирал форму. Для несущественного декоративного aside выбран локальный существующий Sentry ErrorBoundary с пустым fallback и одноколоночным layout; форма находится вне него. Альтернативы повторять загрузку или скрывать общие ошибки приложения отвергнуты: они не гарантируют доступность формы и расширяют область подавления ошибок. Regression до изменения FAIL, после PASS; общий boundary и privacy projection сохраняются.

Загрузка управляемых Passkey отделена от mutation busy: idle/loading/ready/error предотвращают ложное «нет ключей» при pending/failed GET. Существующие Skeleton/Alert/Button дают загрузку, ошибку и retry; пустота утверждается только после successful GET. Новый deferred-promise component regression проверяет отказ и повторный ответ; API/WebAuthn контракт не меняется.

Итог 2026-10-05T14:46:25.6409088+03:00: event закрытия Dialog передаёт отложенный route focus после navigation; previous control восстанавливается только при прежнем pathname. Проверка фактически focused heading предотвращает потерю pending focus при открытом portal. Failed palette assertion сохранён; итоговый full46/10,37components и Sentry browser9 PASS.
