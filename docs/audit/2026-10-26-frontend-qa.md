# Frontend / Visual / Functional QA — 26.10.2026

Стенд: production build (`npm run build`) + preview (Nginx-эквивалент через Vite preview), Chromium (Playwright 1.63), реальный backend и PostgreSQL. Скриншоты с OTP/секретами/персональными данными не сохранялись и не коммитились.

## 1. Проверенные маршруты и состояния

| Маршрут/экран | Anonymous | Authenticated | Admin | Ограниченная сессия | Ошибки/пусто/загрузка |
| --- | --- | --- | --- | --- | --- |
| `/login` | ✔ | redirect | redirect | — | неверный пароль, MFA-шаг, passkey-кнопка, disabled-профиль |
| `/register` | ✔ (open) | redirect | redirect | — | closed, коллизия, код из письма, истёкший код |
| `/verify-email` | ✔ | ✔ | ✔ | — | успех/истёк/неверный код |
| `/` профиль | redirect | ✔ | ✔ | password-change/deletion/legal | loading/empty/error |
| `/account/security` | redirect | ✔ | ✔ | ✔ | TOTP setup/confirm, passkey list/register/delete, recovery, email |
| `/account/sessions` | redirect | ✔ | ✔ | ✔ | read grant, revoke, empty, expired |
| `/account/privacy` | redirect | ✔ | ✔ | ✔ | consent/deletion |
| `/account-deletion` | redirect | ✔ | ✔ | ✔ | request/cancel, keyboard, focus |
| `/admin`, `/admin/users`, `/admin/applications`, `/admin/sessions`, `/admin/audit`, `/admin/system` | 403-заглушка | 403 | ✔ | admin-MFA onboarding | пустые таблицы, пагинация, ошибки, секрет клиента один раз, смена режима |
| `/admin` без MFA | — | — | onboarding | ✔ | TOTP/Passkey enrollment + elevation |
| `/step-up/{token}` | redirect login | ✔ | ✔ | ✔ | allow/deny, passkey/TOTP, expired |
| `/privacy`,`/terms`,`/cookies`,`/data-consent` | ✔ | ✔ | ✔ | ✔ | cookie consent, темы |
| `*` | 404 | 404 | 404 | — | — |

## 2. Визуальная проверка

`frontend/e2e/appearance.spec.ts` покрывает:

- viewport **320, 375 (добавлен в этом аудите), 390, 768 (в resize-сценариях), 1024, 1440, 1908/1920**, высоты 480–1200;
- light/dark/system, сохранение выбора, reload, cross-tab, недоступный storage;
- нижнюю границу footer/cookie-banner без горизонтального переполнения;
- 320px short viewport: скролл модалки, focus isolation, мобильная навигация;
- контраст текста/фокуса для обеих тем (расчётные проверки, WCAG AA-ориентир);
- keyboard: Tab/Shift+Tab/Escape, возврат фокуса, command palette;
- deep links, back/forward, заголовки страниц;
- reduced motion, отказ декоративного chunk без потери входа.

## 3. Функциональные E2E прогоны

| Профиль | Спеки | Результат |
| --- | --- | --- |
| default-off (`FEATURE_*=false`, `REQUIRE_ADMIN_MFA=false`) | sso, multi_client_sso, protocol_lifecycle, telemetry, privacy, appearance, step_up | **50 passed** (sso 6 + остальные 44) |
| enabled (`FEATURE_*=true`, `REQUIRE_ADMIN_MFA=true`) | passkey, totp, privacy, telemetry | **9 passed** |

Ключевые регрессии аудита:

- `sso.spec.ts` 02/04: в форме смены режима регистрации **0** password-полей, в диалоге **1**; операция успешна после одного password+MFA.
- `sso.spec.ts` 06: после reload в пределах 5 минут диалог **не** появляется, GET сессий уходит с сохранённым grant; после logout `sessionStorage` очищен.
- `totp.spec.ts`: реальный TOTP enrollment, reauth, recovery replay и login; два 30-секундных окна, без подмены часов.
- `passkey.spec.ts`: виртуальный authenticator с UV, origin/RP, удаление/замена credential.
- `privacy.spec.ts`: удаление аккаунта, ограниченная сессия, клавиатура/Escape.
- Console/pageerror: ошибок, ломающих сценарии, не зафиксировано; ожидаемые 401 в консоли — часть flow.

## 4. Доступность

- Проверяется `@axe-core/playwright` в privacy/appearance-сценариях (по существующей методике), контраст и focus-visible.
- Все диалоги: role=dialog, aria-label, Escape, focus trap, возврат фокуса.
- Формы: label/for, autocomplete (`current-password`, `one-time-code`), ошибки в `role=alert/status`.
- Ограничение: полный WCAG 2.2 AA аудит всех экранов не проводился; проверены ключевые поверхности и темы.

## 5. Ограничения

- Firefox/WebKit не запускались (Chromium only); это не подтверждает их поведение.
- Нет pixel-perfect screenshot diff: проверки геометрии/контраста/переполнения, а не визуальные снапшоты.
- Мобильная виртуальная клавиатура эмулируется размерами viewport, не реальным устройством.
- Nginx CSP проверяется отдельным тестом (`e2e/csp.spec.ts`) в контейнерном контуре, не в preview.

## 6. Изменения UI в этом аудите

- Диалог reauth: очередь, countdown после повторного TOTP-кода, пояснение одноразовости, корректный возврат к паролю при истёкшем authorization.
- `/admin/system`: убрано второе поле пароля; добавлено объяснение, что подтверждение запросит сервер.
- `sessionStorage` read grant (не отображается в UI, но влияет на частоту диалога).
- Viewport 375 добавлен в appearance-матрицу.
