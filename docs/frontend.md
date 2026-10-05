# Frontend ALXPRGS SSO

Статус миграции: done в локальном scope FRONTEND-REDESIGN-01. Нормативный дизайн — [ALXPRGS Design Language v1](../ALXPRGS%20Design%20Language.md), решения — [ADR0021](adr/0021-frontend-design-platform.md), фактическая приёмка — [implementation report](../FRONTEND_REDESIGN_IMPLEMENTATION_REPORT.md). Официальный artwork локально включён из ALXPRGS assets; provenance/роли — [brand README](../frontend/public/brand/README.md). Итоговые браузерные проверки46default/10enabled прошли; прежний scoped brand2 сохранён в отчёте.

## Архитектура и маршруты

React18 + TypeScript/Vite8; React Router7 BrowserRouter/Routes/NavLink. AppShell предоставляет единственный main, skip-link, theme control, scroll area и cookie banner. Public legal/verify-email доступны до session gate. Для остальных маршрутов loading → password_change → force_login → anonymous → deletion_management/pending → legal acceptance → application. URL не выдаёт права. Backend продолжает independently проверять session purpose, grants и RBAC.

Общий футер находится у нижнего края коротких страниц; на длинных следует за содержимым внутри `.app-scroll`. Эта область — flex column с растущим main, а верхняя панель и футер сохраняют свою высоту. AuthSurface заполняет доступное место без фиксированного вычета из высоты окна. Баннер cookies занимает отдельное место снизу в AppShell; его раскрытие автоматически уменьшает прокручиваемую область, без перекрытия формы или футера. Правило одинаково для публичных страниц, кабинета, администратора и session gates.

| Адрес | Экран |
| --- | --- |
| `/login`, `/register`, `/verify-email` | Вход, регистрация с обязательным подтверждением email, явное подтверждение ссылки |
| `/privacy`, `/terms`, `/cookies`, `/data-consent` | Публичные документы |
| `/` | Профиль |
| `/account/security` | Пароль, доступные TOTP/passkey/recovery/email операции |
| `/account/sessions` | Собственные сессии и отзыв |
| `/account/privacy`, `/account-deletion` | Диагностика и управление удалением |
| `/admin` | Реальные counts, режим регистрации, features, последние события, build identity |
| `/admin/users`, `/admin/applications` | Пользователи и OIDC-клиенты |
| `/admin/sessions` | Поиск пользователя/отзыв всех сессий; глобальный список устройств API не предоставляет |
| `/admin/audit`, `/admin/system` | Фильтр/экспорт/детали аудита, состояние/режим регистрации |
| Неизвестный адрес | Явный экран «Страница не найдена» после обязательных gates |

Смена password/legal/deletion gate не обходится deep link. safe return_to остаётся exact-origin sanitization; /oauth/authorize выполняется сервером. GET /oauth/client-context показывает проверенные сервером name/origin, произвольный query branding не принимается. Администраторские mutation подтверждения UX не заменяют server-bound reauthentication.

## Компоненты и tokens

`public/theme/design-tokens.css` загружается до React; theme.js синхронно выбирает Dark/Light/System с прежним разрешённым local preference и cross-tab handling. Dark default SSO, demos System default. Цвета, fonts, radii, control heights, layout widths, layers и duration/easing — семантические tokens. Tailwind4 Vite plugin генерирует utilities через @theme inline в index.css. Handmade utility stylesheet удалён; legacy palette.css остаётся только для двух demos, SPA его не импортирует.

`components/ui` — Button/IconButton/Input/PasswordInput/OTPInput/Field/native Select/Textarea/Checkbox/Radio, Alert/Badge/Skeleton/EmptyState/CopyButton, Feedback toast/confirmation, Dialog, ActionMenu/Tooltip, DataTable/Pagination. Native label/section-panel являются простыми семантическими эквивалентами Label/surface. Route NavLinks заменяют вкладки: добавление tab role к навигации было бы неверной семантикой. Отдельный Popover не введён без продуктового сценария. Командная палитра cmdk использует общий Dialog. Порталы сохраняют sso-sensitive/data-sentry-block.

Account/admin controllers владеют сценариями/API/loading/error/busy, views — представлением. Для поиска серверная пагинация50; sorting только текущей загруженной страницы и обозначен интерфейсом. Устаревшие ответы поиска игнорируются по request-id. Row action menus доступны клавиатурой. Compact admin controls36px только при desktop fine pointer, touch минимум44px. Mobile table rows становятся подписанными карточками; sidebar становится drawer.

Dialog сохраняет Radix FocusScope, aria isolation и keyboard mechanics. Custom static overlay/scroll-lock/stacked inert устраняет запрещённый CSP inline style из Radix Overlay без расширения style-src. Вложенный proof dialog делает parent inert; Escape/return-focus проверяются. Busy mutations блокируют dismiss. Не подключайте Radix Overlay/react-remove-scroll без новой реальной CSP проверки.

Geist/Geist Mono WOFF2 идут из pinned npm пакета в Vite assets, OFL notice — `/licenses/Geist-OFL.txt`; runtime Google Fonts/CDN отсутствуют. Mono применяется к техническим значениям и OTP. Функциональные иконки — named Lucide imports. Канонический логотип не воссоздаётся произвольной буквой.

## Вход, секреты и motion

При серверном passkey_enabled заметная кнопка «Войти с ключом доступа» доступна до пароля. Без username используется discoverable ceremony; с username — credential allow-list сервера. Сериализация и точный RP/origin/UV verifier не менялись. Conditional mediation исследовано, решение о сохранении explicit ceremony и lifecycle требования записаны в ADR0021. Default-off APIs/UI остаются закрыты.

OTP — один доступный логический input numeric/autocomplete/paste, шесть цифр для TOTP/email; recovery ввод остаётся буквенно-цифровым. Setup QR + ручной secret + copy, recovery one-time visibility/copy и client secret one-time modal очищаются при завершении/закрытии/смене раздела. Bearer/refresh/proof/password/secrets не сохраняются в браузерное storage, telemetry или logs.

Motion: auth-step/layout, modal entry, selected navigation. CSS state/copy/success/skeleton feedback; continuous topology сигналы останавливаются при hidden/reduced motion. Pointer glow: один layout read на entry, максимум один rAF style write, без React render loop. Reduced motion убирает travel/layout/decorative repeats; authentication работает без visual layer. Тема не анимирует первый render, explicit switching имеет короткий CSS переход.

Карточки Infrastructure и SVG-линии используют один набор процентных anchors. Карточки центрируются на этих координатах; SVG без квадратного viewBox сохраняет их положение при любом соотношении сторон панели. Линии проходят под непрозрачными карточками, поэтому видимый конец касается границы карточки. Измерения DOM и ResizeObserver для соединений не нужны.

Декоративный lazy-модуль имеет локальный ErrorBoundary внутри aside: при ошибке загрузки или render визуализация скрывается, форма остаётся доступной, layout становится одноколоночным. Общий boundary критических ошибок приложения сохраняется. Browser regression намеренно обрывает запрос модуля и проверяет сохранение полей и отправку входа; API-ответ в этом case — явно обозначенный UI fixture.

Чтение списка Passkey имеет собственные idle/loading/ready/error состояния, отдельно от регистрации/удаления. Skeleton объявляет загрузку; ошибка предлагает повторить GET; пустой список показывается только после успешного ответа сервера. Disabled capability не запускает GET.

## Проверки

Из `frontend/` после `npm ci`:

```text
npm run lint
npm run typecheck
npm run typecheck:tests
npm run test:unit
npm run test:components
npm run build
```

Обязательные реальные E2E запускаются существующим `python scripts/run_e2e_suite.py` из подготовленной Python среды с guarded PostgreSQL/mandatory fresh marker; профили default-off/enabled имеют preflight на backend и frontend proxy. Точные environment prerequisites — [testing plan](testing/plan.md). Appearance fixtures проверяют геометрию/theme/history/palette/Axe и явно отделены от настоящего PG/browser/WebAuthn. `appearance.spec.ts` содержит Axe WCAG2A/AA/2.1AA/best-practice без disableRules. `csp.spec.ts` запускается за Nginx enforcing CSP; vite-preview не подтверждает CSP. Негативные OIDC/UV/RP/CSRF/replay/proof tests обязательны. Не считайте build/Axe заменой ручной visual inspection или real authentication.
