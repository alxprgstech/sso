# Отчёт о перестройке frontend ALXPRGS SSO

Статус: **done** для FRONTEND-REDESIGN-01. Начало: 2026-10-05T03:52:42.0367906+03:00. Завершение: 2026-10-05T14:46:25.6409088+03:00. Исполнитель: Codex. Ветка: `new/frontend-redesign`. Все 26 критериев локальной frontend миграции подтверждены. Общая production GOAL-09 остаётся отдельной.

[План и точка продолжения](docs/frontend-redesign-plan.md), [архитектурное решение](docs/adr/0021-frontend-design-platform.md), [архитектура и команды](docs/frontend.md), [нормативный дизайн](ALXPRGS%20Design%20Language.md).

## Что реализовано

Перестроены публичные страницы входа, регистрации, подтверждения email, обязательной смены пароля, правовых документов и удаления аккаунта, повторная аутентификация, личный кабинет и административный интерфейс. Сценарии account/admin вынесены в отдельные controllers; представление использует общие компоненты, а состояние допуска к приложению определяется серверным профилем.

Auth на desktop — форма шириной440px и декоративная инфраструктурная схема; на mobile остаётся форма. Личный кабинет разделён на профиль, безопасность, сессии и конфиденциальность. Административный интерфейс имеет sidebar240px, мобильный drawer, обзор, пользователей, приложения, управление сессиями, аудит и конфигурацию. Обзор показывает реальные system/status/audit и build identity. API глобального списка отдельных устройств администратора отсутствует: экран сессий предоставляет существующий revoke-all выбранного пользователя, без выдуманных данных.

Вместо самодельной имитации utilities подключён настоящий Tailwind через Vite. Семантические tokens задают обе темы, фон, текст, границы, состояния, размеры и motion. Нормативные тёмные поверхности090a0c/0f1115/14171d/1a1e26/20252e имеют светлые аналоги; текст и границы контролов адаптированы к проверяемому AA-контрасту. Контролы44px, touch44px, административные desktop строки48px/кнопки36px, радиусы8/10/14/18, длительности120/160/220/280ms. Geist/Geist Mono загружаются локально; OFL license включена в статический артефакт. Chromium CDP подтвердил custom Geist-SemiBold для русского заголовка,14glyphs.

Общие компоненты: кнопки и IconButton, поля/PasswordInput/OTP, Field с labels/descriptions/errors, Select/Textarea/Checkbox/Radio, Alert/Badge/Skeleton/EmptyState, CopyButton, Dialog/ConfirmDialog/Toast, таблица/пагинация/сортировка/меню, навигация и palette Ctrl/Cmd+K. Простые Label/Surface реализованы семантическими native label/section и общими стилями. Неиспользуемый Popover не добавлен. Сортировка таблицы явно относится к текущей загруженной странице; API пагинации сохранён.

Пароль можно показать без submit. OTP — одно логическое числовое поле с autocomplete/paste. Показаны loading/empty/error/success, подтверждение копирования и ошибки повторных попыток. Во время mutation нельзя закрыть busy-dialog или повторно отправить форму. Ошибка logout сохраняет профиль до подтверждённого серверного завершения. Одноразовые пароли, TOTP secrets, recovery codes и client secrets очищаются после завершения, закрытия или смены раздела и не сохраняются в storage.

## Зависимости и архитектурные решения

Добавлены pinned React Router7.18.4, Radix Dialog1.1.23/DropdownMenu2.1.24/Tooltip1.2.16, Motion14.0.0, Lucide1.52.0, Geist1.7.2, cmdk1.1.1; dev Tailwind4.3.3/@tailwindcss/vite4.3.3, user-event14.6.7, Axe Playwright4.13.0, Prettier3.9.9. Официальные peer/licenses/docs проверены до установки. React18 сохранён: Router8 требует React19.2.7. Пакеты MIT/ISC, Geist OFL, Axe MPL2.0. Неиспользуемый Radix Tabs удалён: разделы представлены настоящими маршрутами. Последний npm audit —301packages/0known vulnerabilities.

Компоненты принадлежат source проекта, без генератора и стандартного визуального шаблона shadcn. Radix обеспечивает focus/keyboard/modal semantics. Enforcing CSP обнаружила inline style tag react-remove-scroll из Radix Overlay. Решение: Radix modal Content, статический overlay, CSS scroll lock и небольшой проверенный `inert` stack. CSP не расширялась. Вложенный dialog делает родительский portal inert; после закрытия focus возвращается инициатору. DropdownMenu использует non-modal popup.

Dark — default SSO; явно выбранные Light/System, cross-tab preference и недоступный localStorage работают. Bootstrap темы выполняется до React. Demo сохраняют прежний default System. `palette.css` остаётся только для demos; SSO его не импортирует. Удалены прежний utility stylesheet, manual pathname/pushState routing, tab-state navigation и ручной focus trap. Native product window.alert/confirm отсутствуют; `confirm` в controllers — Promise нашего ConfirmDialog.

## Маршруты и допускающее состояние

BrowserRouter/NavLink/Routes обеспечивают Back/Forward, прямые URL и reload. `/` — профиль; `/account/security`, `/account/sessions`, `/account/privacy`; `/account-deletion`; `/admin` — обзор, далее `/admin/users`, `/admin/applications`, `/admin/sessions`, `/admin/audit`, `/admin/system`. Неизвестный путь показывает404. Public legal/email доступны отдельно. При переходе обновляются title/focus заголовка с учётом lazy загрузки; первый Tab при первоначальном открытии доступен skip-link.

Единый gate сохраняет приоритеты loading → password_change → force_login → anonymous → deletion/limited purpose → legal → application. RBAC проверяется перед lazy AdminPage и независимо сервером. `safe_return_to`, исходный OIDC `/authorize`, точные redirect URI и серверные bindings не заменены клиентской навигацией. Новые telemetry пути внесены только в конечный allowlist; query/hash/unknown IDs отбрасываются. Shell и portals сохраняют Replay blocking.

## Минимальное дополнение backend

Добавлен только GET `/oauth/client-context`: активный клиент, существующий exact redirect validator, rejection duplicate parameters, общий limiter, no-store/common no-cache. Ответ содержит только client_name и redirect_origin без пути/query. Endpoint не создаёт cookie, session, grant или authorization code и не заменяет `/authorize`. Query-параметры name/logo не считаются доверенным брендингом. PostgreSQL regression проверяет положительный ответ/отсутствие session/code/cookie и rejection mismatch/query suffix/origin/inactive/unknown/duplicates. API snapshot и документация обновлены.

OAuth/OIDC verifier, token endpoint, MFA cryptography и схема БД не менялись. Passkey остаётся явной заметной первой кнопкой при разрешающей capability. Discoverable вход поддержан сервером; для non-discoverable используется username. Conditional mediation исследована по W3C/browser docs: pending browser ceremony и server challenge5min требуют отдельного bounded lifecycle/abort/expiry/race покрытия. Автоматическая выдача/обновление challenges при просмотре страницы в этой миграции не добавлена; это инженерное решение, не утверждение о несовместимости протокола. Resident preferred и обязательный UV сохранены.

## Доступность, responsive и производительность

Проверены programmatic labels/descriptions/errors, keyboard trap/Escape/return focus, parent inert, menus, palette search/Arrow/Enter/Escape, skip-link, role-filtered навигация, responsive таблицы, ошибки и контраст. Axe проверяет WCAG2A/AA/2.1AA/best-practice без выключения правил. Декоративная схема не является интерактивным auth-контролом. Reduced motion убирает travel/повторы; при hidden document схема останавливается. Pointer glow измеряет bounds на входе и записывает styles максимум один раз в rAF без React rerender на каждом движении.

Созданы26 локальных screenshots UI-fixtures обеих тем. Через view_image действительно инспектированы: dark Login desktop1440x900, populated Admin Users dark desktop, Admin Applications light desktop, Security обеих тем, Users dark mobile390x844, Password dialog light mobile, Register dark320x480, palette light desktop и Sessions320x360. Для короткого экрана форма/контент прокручиваются над cookie-панелью; не заявляется, что всё помещается одновременно. DOM диагностика320px после исправления header: clientWidth/scrollWidth320/320, offenders0. Эти fixture screenshots показывают layout; настоящие auth доказательства получены отдельными server/PG/Nginx browser campaigns.

Обычный итоговый build: CSS39.95kB(gzip7.71), entry55.18kB(gzip16.33), shared Dialog454.71kB(gzip151.11), общий esm190.10kB(gzip61.88), lazy Admin87.43kB(gzip27.17), Dashboard43.37kB(gzip12.90), palette13.66kB(gzip5.56), Infrastructure3.44kB, fonts69.65/71.36kB. Исходный build: CSS12.05kB(gzip3.28)/entry568.67kB(gzip174.63). Entry55.18kB не равен всему initial transfer: shared chunks загружаются отдельно. Warning>500kB отсутствует. Release Debug ID добавляет около0.48kB на JS chunk; offline build/private map gate прошёл, публичные `.map` удалены штатным проверяющим script. Source соответствует рабочему diff, а не новому immutable release SHA; upload/release не выполнялись.

Локальная4s Chromium диагностика со схемой и реальным pointer hover:241frames, p95frame16.8ms,0longtasks, ввод остаётся доступным, pointer style действительно изменяется. Это локальная проверка отзывчивости, не Lighthouse и не универсальный benchmark. Network/paint/Lighthouse и Safari/Firefox/hardware матрица не измерены.

## Фактические проверки и воспроизведение

Стенд: Node24.20.0, Python3.12.14, PostgreSQL16.15 UTF8/SCRAM/loopback5433 с отдельным новым data directory, Alembic0001→0010 и mandatory local-fresh marker; Nginx1.30.5 и Chromium. Повреждённый Cyrillic launcher `.venv` заменён существующим `.venv-sentry`, зависимости/инструкции глобально не менялись. Приватная DB конфигурация находится вне репозитория и не приводится в отчёте.

| Проверка | Фактический результат |
| --- | --- |
| `npm --prefix frontend run lint`, `typecheck:tests` (включает source), `build` | PASS на итоговом source |
| `npm --prefix frontend run test:components` |37PASS,6.42s после последнего focus исправления; прежние результаты сохранены в worklog |
| `npm --prefix frontend test` |13PASS |
| Ruff check/format изменённых Python3files, canonical mypy | PASS; mypy68files |
| Новый client-context PostgreSQL regression |1PASS,0.88s; также входит в полный набор |
| `pytest tests/test_documented_api_contract.py` документированных routes |1PASS; cache-only permission warning, не функциональный отказ |
| Итоговый полный default-off, campaign73f23772a99b42ea9c95d2873611a21c |46PASS,1.7m; включает отрицательный decorative chunk regression |
| Предыдущий CSS/mobile + CSP campaign e9b9a11137cd447686f4268360b68bce |33PASS,53s; пересекается с прежним43, числа не суммируются |
| Итоговый полный enabled MFA/privacy/CSP, campaign73f23772a99b42ea9c95d2873611a21c |10PASS,1.3m |
| Scoped brand hash/currentSrc/theme/viewport/motion-settled screenshots, campaign31d783db69ee46d5994cd49f6ae1e846 |2PASS,3.8s на brand срезе06:36; дополнено только ожидание окончания анимации в тесте, тогдашний product source не менялся |
| Offline release build + `python scripts/check_sentry_build.py` | PASS после итогового focus source: build3.04s, Debug IDs/symbolication/no-public-maps; без upload |
| `npm --prefix frontend run test:telemetry:browser` |9PASS,22.0s на итоговом source в штатном unrestricted Windows запуске |
| `python scripts/check_secret_scan.py --self-test` |137candidates/0new; synthetic control rejected, baseline не менялась; итоговый повтор после fixture annotation137/0new PASS |
| Полный `pytest tests -q --tb=short` с DB guard |623PASS/2FAIL/5external-email deselected/16subtests,315.28s; два Windows lifecycle failures описаны ниже |
| Отдельный `pytest tests/test_server_lifecycle.py` вне restricted token |19PASS,13.07s; исходные tests/source не менялись |
| Повтор полного pytest вне restricted token |625PASS/5external-email deselected/16subtests,297.08s; только существующий FastAPI/Starlette deprecation warning |

Локальные ignored runner files `artifacts/frontend-redesign/run_with_pg.py` и `run_nginx_browser.py` задают только собственную изолированную DB, SMTP capture и Nginx с repository CSP. Это environment adapters, не замена штатных проверок. Нельзя запускать PG наборы конкурентно на одной DB. Для владельца обычные команды/профили описаны в docs/frontend.md и docs/testing/plan.md.

## Ошибки, исправления и ограничения evidence

Ранние browser campaigns падали на inline-style CSP, устаревших адресах/копии, промежуточном цвете перехода, регистрации inert до появления portal, неверном cmdk label, heading order EmptyState и переполнении header320px. Исправлены первопричины либо фактические маршруты/локаторы тестов. Assertions контраста, безопасности, focus/keyboard и role denial сохранены; retries/skip/xfail не добавлены. После последнего CSS slice auth был проверен полным default43 отдельно, presentation повторена33/CSP и полный enabled10. Числа пересекающихся наборов не складываются.

Первый полный pytest в restricted Windows token: `test_real_server_lifecycle_and_port_release` порт59253 и `test_real_frontend_lifecycle_and_port_release` порт52938 остались заняты после taskkill. Проверены точные PID/listener/commandline собственных tests; только они остановлены штатно вне restricted token. Тот же неизменённый lifecycle19 прошёл в этом режиме. Повтор полного набора625PASS/16subtests прошёл без source/test изменений; первоначальный FAIL сохранён в журнале и отчёте. Наблюдаемые Windows permission/cache warnings отделены от результата приложения.

Secret scanner выявил три ложных сигнала: синтетический QR field, prose UI-selector в supplied FRONTEND_UI_DISCOVERY.md и после форматирования фиксированный analytics client_secret из prepare_e2e_data.py в privacy E2E. Последний итоговый scan138/1new был FAIL до точечных fixture pragmas. Добавлены только точечные detect-secrets pragmas, содержательные assertions/описания сохранены; baseline и правила scanner не расширены. Synthetic control продолжает отвергаться.

## Дополнение UI-LAYOUT-01 от 05.10.2026

По замечанию владельца общий футер прижат к нижнему краю коротких страниц; длинные страницы сохраняют естественную прокрутку после содержимого. Main растёт внутри flex column, высота баннера/футера определяется CSS без вычета170px. Infrastructure задаёт единые процентные координаты SVG-линий и центров карточек. Уточнение внесено в GOAL/frontend/operator/ADR; исходный Design Language остаётся reference, текущий макет описан явно.

Приёмка этого дополнительного diff: 37 UI browser PASS на production preview, 37 component PASS, lint/types/test-types/build PASS; реальные PNG1920×1080/1440×900/390×844 инспектированы. Геометрические regressions до изменения2FAIL, после2PASS. История dev-browser35PASS/2FAIL и исправления readiness/четырёх signal элементов — в [acceptance](docs/acceptance.md) и worklog. API fixtures не подтверждают реальный backend/PG/OIDC/CSP; прежние результаты миграции ниже относятся к прежнему проверенному срезу, не новому diff.

## Матрица26 критериев

| № | Критерий | Evidence / статус |
| --- | --- | --- |
| 1 | Сборка | PASS normal/release offline build |
| 2 | Static/lint/type | PASS ESLint/TypeScript/Ruff/mypy |
| 3 | Unit/component | PASS13/37 |
| 4 | Backend/integration | PASS endpoint/контракт + full625/16subtests; история restricted-token failures сохранена |
| 5 | Playwright/browser | PASS итоговый full default46/enabled10 (73f23772a99b42ea9c95d2873611a21c); прежний scoped brand2 |
| 6 | Сохранённые auth сценарии | PASS реальные2SSO clients/force login/max-age/state/nonce/reauth/limited privacy, enabled WebAuthn/TOTP/recovery |
| 7 | Back/Forward/deep links | PASS route/history/title/reload/404 tests |
| 8 | Псевдо-Tailwind устранён | Старый utility слой удалён |
| 9 | Настоящий Tailwind | Vite plugin/@import/@theme/generated CSS, buildPASS |
| 10 | Общие компоненты | Source-owned UI с реальными consumers/controllers |
| 11 | Темы/старт | PASS dark/light/system/startup/storage/cross-tab tests |
| 12 | Auth дизайн | AuthSurface/Geist/44px/OTP/topology; visual/browser PASS, canonical artwork и сохранение формы при failed decorative chunk |
| 13 | Passkey UX | Capability CTA/username/discoverable; настоящий enabled WebAuthn PASS, UV обязателен |
| 14 | Account/security | Маршруты/flat sections/TOTP QR/copy/one-time recovery, browser PASS |
| 15 | Admin shell | Sidebar/drawer/overview/routes/real tables, visual/browser PASS |
| 16 | Palette | PASS CtrlK/search/no-results/Arrow/Enter/Escape/role filtering |
| 17 | Native alert/confirm | Source scan: window.alert/confirm отсутствуют, продуктовый Promise Dialog |
| 18 | Состояния | Loading/empty/errors/retry/busy/success/copy; deferred Passkey GET failure/retry regression и все37components/browser PASS |
| 19 | Motion | Auth/layout/dialog entry/nav/topology; visual/browser PASS; exit animation не заявлена |
| 20 | Reduced motion | PASS browser reduced profile; hidden handler/CSS pause, no pointer loop |
| 21 | Инспекция layouts | Реальная инспекция desktop/mobile/320x360/320x480 и dialog обеих тем |
| 22 | Accessibility | Axe без исключений + keyboard/focus/inert/labels/контраст PASS |
| 23 | Официальный бренд | PASS same-owner official assets/pinned source SHA; реальные local bytes/hash/currentSrc/viewport/favicon/no-external-image tests2 и инспекция renders |
| 24 | Legacy удалён | Старые routing/focus trap/utilities/tab subsystem заменены; demo palette сохранена по назначению |
| 25 | Security contracts | PASS настоящий OIDC/MFA/CSP/privacy/PG evidence, full625/16subtests и real SDK harness9; ослабления отсутствуют |
| 26 | Правдивый отчёт | Данный отчёт отделяет выполненное, failed/pending и внешние ограничения |

## Итог frontend миграции и границы приёмки

Первоначальный input blocker снят дополнительной read-only проверкой GitHub organization API: same-owner ALXPRGS assets repository содержит канонический SVG и avatar/icon. Source commit9b0eec08898a2eb2a02a66d895055c6ec7d97051, original byte-exact файлы и производный compact vector viewport включены локально. Auth/navbar/core/mobile/favicon используют реальные artwork без recoloring. [Provenance/роли](frontend/public/brand/README.md). Полный итоговый default46/enabled10 и прежний scoped brand2 PASS. Дополнительно инспектированы стабильные после motion dark/light auth1440x900 и mobile320x480, а также обновлённые admin/navbar и password dialog. SVG navy wordmark читаем на светлой backing; это presentation surface, цвета artwork не менялись. Четыре brand screenshots дополняют прежние26 layouts. Modern favicon использует2355byte SVG; исходные PNG fallback/Apple icon не нужны в обычном initial render.

Сохранены без намеренного ослабления: Authorization Code+PKCE S256, exact redirect/issuer/audience/time/signature/state/nonce, одноразовость/refresh rotation/replay, CSRF/RBAC, action/user/session/payload bound reauth, WebAuthn UV/origin/RP/challenge/signature, обязательный signup email, server default-off flags, limited/deletion/legal gates и telemetry secret filtering/Replay blocking. UI fixtures не выданы за криптографию или настоящую интеграцию.

Production HTTPS/реальная внешняя доставка email, Docker/Linux runtime текущего diff, remote CI и hardware/browser matrix не подтверждены этой задачей. SMTP capture — локальный synthetic receiver. Пять внешних email tests deselected согласно исходному opt-in CI-03 профилю; это не evidence доставки. Commit/push/PR/tag/release/deploy/реальная рассылка не выполнялись. Общая GOAL-09 и production приёмка не закрываются миграцией frontend.


Итоговая уборка стенда: два uvicorn distributed-rate-limit теста из первоначального restricted запуска остались с idle PG connections, поскольку существующий fixture подавляет cleanup exceptions. Они идентифицированы по PID/parent/creation/source/listener и остановлены отдельно; functional assertions межпроцессного лимита прошли также в полном unrestricted повторе. Возможность улучшить диагностику cleanup зарегистрирована FR-08 вне обязательной frontend приёмки. После проверки точных PG executable/data/PID/time/port и нуля других клиентов собственный кластер штатно остановлен; все порты кампании свободны, данные сохранены. Первоначальные safe-refusal проверки путей/precision и активных клиентов не обходились.


## Окончательный аудит и исправленные отрицательные сценарии

Первоначальный срез 06:36 преждевременно называл все критерии подтверждёнными. Последующая проверка выявила два непокрытых состояния: failed lazy Infrastructure заменял форму общим error fallback; список Passkey показывал пустоту во время pending/failed GET. Это зафиксировано до исправлений в worklog, Goal оставалась active.

Browser regression на failed decorative module до исправления:1FAIL13.1s; после локального ErrorBoundary:1PASS6.7s, затем вошёл в полный46. Форма остаётся доступной и отправляет вход без декоративного aside. Ответ401 в этом отдельном case — UI fixture, не доказательство криптографии. Общий boundary приложения сохраняется.

Passkey deferred GET regression до изменения:1FAIL6.53s. Первая попытка после изменения:36PASS/1FAIL10.23s из-за неподдерживаемого data-testid на Alert; locator исправлен на фактический текст. Затем37PASS10.07s, итоговый повтор37PASS6.42s. GET имеет отдельные idle/loading/ready/error состояния, Skeleton, error/retry и empty только после successful response; WebAuthn API и verifier не менялись.

Полный campaign4f2a53d3cbcb4be6b64a5faf5adbfafc:45PASS/1FAIL3.1min, enabled не запускался после default failure. Заголовок после перехода из палитры был видим, но opener получал focus из delayed Dialog close handler. Исправлена передача focus: pathname change передаёт его RouteFocus после закрытия; обычный/nested dismiss возвращает инициатору. Сохранены прежний focused-heading assertion, keyboard и nested isolation проверки. Итоговый полный campaign73f23772a99b42ea9c95d2873611a21c:46PASS/1.7m и10PASS/1.3m; retries/skips/assertion weakening отсутствуют.

Scanner сначала сообщил143candidates/6new, затем142/5new: публичные Git commit/SHA256 provenance hashes. Источник и bytes отдельно проверены; только точные строки получили штатные allowlist annotations, в валидном JSON — строки-note с поддерживаемым // delimiter. Baseline/plugins не менялись; synthetic secret control отвергается. Итоговый повтор после текущих исходников и документации:137candidates/0new PASS. Приватные значения не выводились.

Итоговые offline release/private map и реальный SDK privacy9/22.0s повторены после последних исправлений. Собственный стенд остановлен после PID/executable/data/UTC ticks/port/0clients guards; проверяемые порты свободны, данные сохранены. UTF-8/local links и git diff --check PASS. Работа сохранена в локальном diff без commit/push/PR/deployment.
