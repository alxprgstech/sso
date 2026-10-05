# Перестройка frontend — FRONTEND-REDESIGN-01

Начало: 2026-10-05T03:52:42.0367906+03:00. Исполнитель: Codex. Ветка: `new/frontend-redesign`.
Нормативный дизайн: [ALXPRGS Design Language v1](../ALXPRGS%20Design%20Language.md). Задание владельца от 05.10.2026 охватывает весь frontend; общая приёмка SSO остаётся отдельной.

| ID | Приоритет | Зависимости | План / критерий готовности | Статус |
|---|---|---|---|---|
| FR-01 | P0 | — | Изучить source/tests/API/OIDC/MFA/privacy/CI, записать карту инвариантов и решения по официальным документациям | done |
| FR-02 | P0 | FR-01 | Tailwind/Vite, семантические tokens, локальные Geist/brand, Lucide/Motion, headless source-owned primitives; type/lint/component/build | done |
| FR-03 | P0 | FR-01, FR-02 (без artwork) | Router/history/deep links/404; server gates и safe return_to; regression tests | done |
| FR-04 | P1 | FR-02 (без artwork), FR-03 | Auth/register/email/forced-password/legal/deletion/reauth; passkey/OTP/motion/labels, прежние сценарии | done |
| FR-05 | P1 | FR-02 (без artwork), FR-03 | Account/security/sessions/privacy и admin sidebar/overview/users/apps/sessions/audit/system, tables/command palette | done |
| FR-06 | P0 | FR-04, FR-05 | Полный applicable static/components/browser/PG, security/privacy/CSP, реальные responsive/theme/keyboard/reduced-motion render проверки; удалить legacy | done |
| FR-07 | P1 | FR-06 | Актуальные README/routes/operator docs, отчёт с evidence и всеми 26 критериями; цель закрывается только при их выполнении | done |

Каждый этап проверяется до накопления следующего. Моки компонентов отделены от настоящего backend/PG/WebAuthn/E2E. Backend меняется только при доказанном минимальном контрактном пробеле. Секреты остаются в памяти, весь shell и portals сохраняют Replay blocking. Native confirmation заменяется продуктовым диалогом, связанная reauthentication остаётся серверной.

## Точка продолжения

Все обязательные этапы FR-01–07 выполнены; актуальный итог и время завершения приведены в последней записи ниже и implementation report. Изменения сохранены в локальном diff ветки `new/frontend-redesign`; следующий шаг — review владельцем. Стенд остановлен, официальный бренд включён. FR-08 — отдельное запланированное улучшение диагностики тестового cleanup, вне этой Goal.

## История контрольных точек

FR-02: foundation выполнен и проверен, но официальный artwork отсутствует. Условие разблокировки — канонический SVG и mark/avatar либо официальная ссылка владельца; ранее отправленный запрос остаётся актуальным. Зависимые сценарии реализованы независимо от artwork; причина изменения зависимостей — бренд не влияет на проверяемые auth/protocol contracts.

FR-03–05 завершены на проверенном браузерном срезе 2026-10-05T05:46:21.660433+03:00: default43/43, финальные UI/CSP33/33, enabled10/10, component36/36, unit13/13. Фактическое начало общей задачи указано выше; промежуточные изменения/проверки — в worklog.

2026-10-05T05:54:30.2964766+03:00: FR-06/07 ещё выполняются. Полный PostgreSQL набор623PASS/2FAIL (только остановка процессов Windows restricted token); после проверки принадлежности и остановки двух собственных listener процессов отдельная lifecycle группа19/19 PASS вне restricted token. Полный набор повторяется в этом режиме без изменения source/tests/guards. Дополнительно проверяются существующие offline Debug ID/private map gate и настоящий Sentry privacy harness, без ingestion. Далее: окончательные результаты/ссылки/secret scan и штатная остановка собственных PG/Vite. Общая цель остаётся открытой из-за критерия23; остальные проверки не подменяются этим блокером. Commit/PR/deploy не поручены.


2026-10-05T06:07:05.330297+03:00 — завершение независимых FR-06/07: full625/16subtests, lifecycle19, telemetry browser9, normal/release offline build/static/component36/unit13/real default43/finalUI33/enabled10 PASS. Документы проверены на UTF-8 и94 local links в15 файлах (итоговый scanner/diffcheck фиксируются в worklog после исполнения). PG/backend/Nginx/SMTP/Vite остановлены с guards; порты свободны. Следующий необходимый шаг — официальный asset для FR-02/критерия23; цель не завершена.

| ID | Приоритет | Зависимости | Критерий готовности | Статус |
|---|---|---|---|---|
| FR-08 | P2 | FR-06 | Отдельная будущая задача: distributed-rate-limit fixture должен явно диагностировать отказ cleanup и проверять завершение owned child tree. Функциональные rate-limit assertions сохраняются. Не входит в обязательные критерии текущей frontend миграции; выявлено при restricted Windows запуске. | planned |

2026-10-05T06:10:06.6670019+03:00 — окончательное завершение FR-06/07 после final scanner137/0new/self-test/ESLint/UTF-8links95/whitespacePASS. Предыдущий срез06:07 сохраняет последовательность выполнения; текущий обязательный следующий шаг только FR-02 official artwork.

2026-10-05T06:13:20.4145843+03:00 — найден official GitHub assets repository через same-owner organization API; blocker FR-02 снят, implementation/verification официального artwork in_progress. Предыдущие dated blocker записи сохранены как история.


2026-10-05T06:36:32.386584+03:00 — FR-02 artwork implementation/browser/visual завершён: source provenance, actual assets45default/10enabled/2brand PASS,36components/build/static/release maps PASS. Все26 критериев отражены в отчёте; статусы FR-02 и общей задачи done оформляются после final scanner/docs/whitespace checks. Исторический blocker снят, owner input не нужен. FR-08 остаётся отдельным planned follow-up и не входит в эту Goal.



2026-10-05T14:46:25.6409088+03:00 — FR-01–07 done; общая FRONTEND-REDESIGN-01 завершена. Последние отрицательные состояния и focus race исправлены, full46/10,37components/13unit/private maps/Sentry9/scanner/docs PASS. Исторические blocker/premature/failure записи выше сохранены; artwork input больше не требуется. Собственный стенд штатно остановлен с guards. Следующая точка: review локального diff; FR-08 остаётся planned отдельной задачей без обязательного остатка в этой Goal. Production/remote CI/live mail не заявлены.
