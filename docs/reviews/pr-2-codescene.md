# Анализ CodeScene для PR #2

Исполнитель: текущая рабочая сессия. Начало: 2026-10-03T19:49:41.9617228+03:00. Завершение анализа: 2026-10-03T19:57:34.929204+03:00. Ветка `new`, ревизия `3dbd10b6765260ead3ffe9f1eb6b4357430b6348`; [PR #2](https://github.com/alxprgstech/sso/pull/2).

## Вывод

Замечания по сложности в основном обоснованы. Часть новых функций объединяет несколько самостоятельных обязанностей; особенно важны повторная аутентификация, WebAuthn, фокус диалогов и backup/restore. До слияния рекомендуется рефакторинг с сохранением поведения и отрицательных проверок безопасности.

CodeScene сообщает о сопровождаемости и риске будущих изменений. Само наличие Complex Method или critical rule не доказывает текущую уязвимость, потерю данных или падение функционального теста. В этом анализе конкретный обход защиты не воспроизведён; это не полный аудит безопасности.

Получены все 35 inline-комментариев PR: 13 разных файлов. Категории пересекаются: AccessibleDialog присутствует и среди нового кода, и среди critical rules. Число правил в сводной таблице означает виды проблем, а не всегда число функций: например, privacy_service имеет 13 комментариев и четыре вида правил.

Приложенное письмо содержит тот же набор оценок и уведомления о строках кода. Оно ссылается на запуск 7798843, исходный текст владельца — на 7798850; это не две отдельные совокупности дефектов. Inline-комментарии GitHub подтверждены для текущего HEAD 3dbd10b. Транспортные заголовки и адреса из письма в журнал не перенесены.

## Почему gates не прошли

- Prevent hotspot decline: mfa_service 6.81 → 6.22, run_e2e_suite 7.93 → 7.89. Оценка существующих hotspots снизилась.
- New code is healthy: десять новых файлов ниже заданного в отчёте порога 10.00. Высокий балл 9.69 всё равно не проходит такой порог; название профиля The Bare Minimum не означает, что порог нового кода мягкий.
- Enforce critical code health rules: AccessibleDialog и backup_db содержат по два блока вложенной логики, отмеченных Bumpy Road Ahead. «Critical» здесь — категория правила качества, не классификация уязвимости.
- Улучшение verification_email 8.63 → 9.19 и run_overnight_stability 2.47 → 2.58 не компенсирует провал независимых gates. Второй файл остаётся с низкой оценкой, хотя направление изменения положительное.

Официальные определения: [Code Health](https://docs.enterprise.codescene.io/versions/7.0.4/guides/technical/code-health.html) и [PR integration / quality gates](https://docs.enterprise.codescene.io/versions/7.0.4/guides/pr-integration/integrate-into-ci-cd.html). Complex Method считает сложность ветвления; Complex Conditional — составные логические выражения; Bumpy Road — несколько участков вложенной логики, объединённых в одной функции. Источник — документация версии 7.0.4; версия анализатора проекта и полная конфигурация правил недоступны через report URL.

## Проверка конкретных файлов

Приоритет обозначает очередность рефакторинга, а не наличие подтверждённого дефекта безопасности. Числа сложности и пороги ниже получены из inline-комментариев, а не из самостоятельного запуска CodeScene.

| Файл / место | Оценка / наблюдение | Обоснованность и предлагаемый шаг |
| --- | --- | --- |
| [mfa_service.py](../../backend/app/services/mfa_service.py), WebAuthnService.verify_authentication, строки 418–542 | 6.81 → 6.22; сложность 21 → 29 при пороге 9; составные условия также в TOTP | Высокий приоритет. Разобрать загрузку credential, разрешение challenge, криптографическую проверку и погашение/аудит на именованные этапы. Сохранить purpose, точное binding expected_challenge/user, origin/RP/UV, locks, sign_count, одноразовость и единую транзакцию для commit=False. TOTP replay проверку сохранить, условие описать понятным доменным правилом. |
| [privacy_service.py](../../backend/app/services/privacy_service.py), строки 146–362 | 6.69; start_reauthentication 20, confirm_factor 13, factor_methods 10, request_deletion 9; mean 5.88 при пороге 4; confirm_factor 9 аргументов | Высокий приоритет. Отделить проверки аккаунта/сессии и пароля, политику срока/паузы, выдачу permission и проверку конкретного MFA. Типизированные команды и контекст могут сократить аргументы по смыслу. Сохранить порядок locks/commit, persisting failed attempts, hash/rotation/action/session/TTL и last-admin invariant. Полный отказ при отключённом обязательном факторе обязателен. |
| [AccessibleDialog.tsx](../../frontend/src/components/AccessibleDialog.tsx), строки 3–25 | 9.24; сложность 19 при пороге 10; два вложенных блока | Высокий приоритет. Несмотря на малое число строк, обработка Escape, границ Tab, отсутствие controls и возврат фокуса сжаты в одном effect. Разделить выбор controls, решение перемещения фокуса и жизненный цикл обработчика. Проверить busy, динамическое отключение controls, пустой диалог, удалённый trigger и cleanup; не убирать keyboard trap ради метрики. |
| [backup_db.py](../../scripts/backup_db.py), main, строки 32–182 | 9.49 → 9.11; два вложенных блока | Высокий приоритет для эксплуатации. CLI, Docker/native dump, экспорт журнала, проверка результата и cleanup находятся в main. Вынести создание команд и выполнение этапов, оставить main координатором. Сохранить явный выбор сервера, отсутствие fallback на другой сервер, закрытый вывод ошибок и удаление неуспешного dump. |
| [privacy_journal.py](../../scripts/privacy_journal.py), restore_sql, строки 15–55 | 9.10; сложность 14 при пороге 9; составные условия дат | Высокий приоритет вместе с backup. Разделить валидацию формата/свежести журнала, нормализацию UUID/дат и создание SQL. Сохранить UTC, окна пять минут/30 дней, отсутствие произвольного SQL и применение в транзакции dump; не заменять свежий журнал устаревшим sidecar. |
| [consent.ts](../../frontend/src/telemetry/consent.ts), readPrivacyChoice, строки 11–27 | 8.55; сложность 15 при пороге 9; условие с восемью ветвями | Средний приоритет. Проверки нужны; разделить структурную проверку unknown JSON, версии, времени и зависимости Replay от diagnostics. Сохранить отказ по умолчанию, memory fallback и отзыв при недоступном storage. Простая замена if на большую .every-маску сама по себе не улучшает смысл. |
| [PrivacyControls.tsx](../../frontend/src/components/PrivacyControls.tsx), CookieBanner, строки 13–68 | 9.00; сложность 37 при пороге 10 | Средний приоритет, существенное разделение обязанностей. Отделить browser subscriptions/state, измерение высоты, настройки и отображение действий. Сохранить browser-only выбор, staging/production policy, отзыв/вкладки, reserved scroll area и focus return. JSX/optional chaining дают часть метрики, но обязанности действительно смешаны. |
| [run_e2e_suite.py](../../scripts/run_e2e_suite.py), run_e2e, строки 37–323 | 7.93 → 7.89; анализатор сообщает рост длины 241 → 252 при уже высокой сложности | Средний приоритет. Есть повторение seed/start/preflight/Playwright/stop для двух профилей. Общий сценарий одного профиля с явным списком тестов упростит runner. Сохранить обязательные return codes, default-off/enabled, отказ preflight и остановку процессов; новый список тестов не должен стать необязательным. |
| [LegalPage.tsx](../../frontend/src/pages/LegalPage.tsx), AcceptancePage, строки 31–51 | 9.39; сложность 13 при пороге 10; составное условие формы | Невысокий приоритет. Отделить отправку согласий/ошибки/переход после сохранения от JSX. Сохранить два пустых checkbox, серверные версии, sanitizeReturnTo и допуск перехода только к oauth authorize. |
| [0004_privacy.py](../../backend/alembic/versions/0004_privacy.py), upgrade, строки 13–114 | 9.46; 97 строк при пороге 70 | Невысокий риск поведения: преимущественно декларативный DDL. Разбить по сущностям на функции внутри этой исторической миграции. Не импортировать изменяемые ORM models, не менять revision/DDL/очерёдность, не добавлять вложенные commits; upgrade/downgrade и необратимую минимизацию проверить на PostgreSQL. |
| [appearance.spec.ts](../../frontend/e2e/appearance.spec.ts), mockUI, строки 26–44 | 9.58; сложность 15 при пороге 9 | Невысокий риск приложения, влияет на тестовый стенд. Явные обработчики method/path вместо длинного else-if. Сохранить ошибку для неизвестного маршрута, узкий /api/v1 matcher и обозначение mock UI; не выдавать эти проверки за реальные auth/PG. |
| [api/privacy.py](../../backend/app/api/privacy.py), строки 97–175 | 9.69; четыре handlers имеют 5/5/7/7 аргументов при максимуме 4 | Наиболее зависимое от framework замечание: многие аргументы — Depends, Request/Response. Объединить действительно общий request/auth context через типизированную dependency и оставить payload явным. Сохранить исходные Depends/CSRF и допуски restricted sessions; не удалять защитные dependencies ради числа аргументов. |
| [AccountDeletionPage.tsx](../../frontend/src/pages/AccountDeletionPage.tsx), submit, строка 40 | 9.69; guard !proof, factor_required, !confirmed | Невысокий приоритет: guard важен и понятен. Описать именованную готовность к подтверждению или разделить guard clauses. Сохранить явную галочку, завершение фактора и серверную авторизацию; реальный бизнес-сценарий этим замечанием не опровергнут. |

## Предупреждение о совместных изменениях

Absence of Expected Change Pattern для run_e2e_suite/manage_test_server — историческая связь файлов. По текущему diff runner добавляет списки тестов и PRIVACY_ENABLED_PROFILE, не меняя CLI lifecycle tools. manage_test_server сохраняет унаследованное окружение и поддерживает прежние default-off/enabled. Обязательного пропущенного изменения по этой причине не найдено. Полный запуск runner после рефакторинга нужен для подтверждения; изменять второй файл ради статистической пары не требуется.

## Покрытие и проверки при дальнейшей работе

Проверено чтением, не новым прогоном:

- tests/integration/test_privacy_pg.py: сроки/отмена/пауза, permission binding/expiry/reuse, CSRF/пароль, TOTP replay, competing requests/worker и последний администратор.
- tests/integration/test_passkey_pg.py и frontend/e2e/privacy.spec.ts: default-off, действительная криптография/negative checks и браузерный enabled профиль с UV.
- frontend/src/Privacy.component.test.tsx: malformed/expired choice, storage failure при отзыве, отдельный Replay, вкладки, Tab/Shift+Tab/Escape и возврат фокуса. Проверки busy/пустого диалога/динамических controls следует дополнить при рефакторинге.
- tests/test_privacy.py и tests/test_ops_backup_restore_totp.py: journal normalization/свежесть/retention, настоящее восстановление с удалённым после backup субъектом и сохранением данных действующего пользователя.
- frontend/e2e/appearance.spec.ts и реальный privacy E2E: раскладка, темы/клики/CSP и функциональная навигация.

Предлагаемый порядок: (1) WebAuthn + privacy reauth, (2) диалоги + backup/journal, (3) cookies/consent, (4) runner, (5) остальные небольшие места. После каждого блока выполнить соответствующие положительные и отрицательные регрессии; для locks/races/backup использовать PostgreSQL, для WebAuthn — настоящий виртуальный authenticator с UV. Затем Ruff/mypy/frontend typecheck/lint/build, миграции, общий необходимый E2E и повторный CodeScene для нового HEAD.

Запуск CodeScene на новом коде — критерий успешного устранения его gates; простое извлечение helpers и зелёные функциональные тесты не гарантируют оценку 10.00. Приёмочный порог и правила в этой задаче не менялись.

## Ограничения выполненного анализа

Report UI CodeScene не удалось открыть, но полный предоставленный отчёт, письмо и все 35 inline-комментариев доступны. Прочитаны отмеченные функции и связанные тесты на текущей ревизии. Новых функциональных тестов, CVE-аудита или CodeScene CLI не запускалось. Реализация не изменена, suppression/установки/merge/push не выполнялись. Сохранены только локальные результаты анализа и рабочие документы.


## Исправления по поручению владельца — 2026-10-03T21:17:43.813587+03:00

Коммит [921ddcb](https://github.com/alxprgstech/sso/commit/921ddcbf57884a6c1717f8965409cafc2eea2b73) устранил оба CI failures; [CI37143192991](https://github.com/alxprgstech/sso/actions/runs/37143192991) полностью success. Cookies занимают нижнюю CSS flex-строку без JS reserve; строгие геометрические assertions сохранены, добавлены repeated resize и отсутствие ResizeObserver. Ruff применяется ко всему CI scope. Рефакторинг сохраняет trust policy/UV, CSRF, password/MFA, UTC deadlines, блокировки и одноразовость; все обязательные проверки остаются в CI.

Первый повтор CodeScene [7799296](https://codescene.io/projects/85555/delta/results/7799296) подтвердил два passed gates и девять новых файлов10.00; остался один Complex Method verify_reauthentication (10 threshold9). [8b3e958](https://github.com/alxprgstech/sso/commit/8b3e958933f98ead16767b11335ffbeb1d4924c3) разделяет session и password/email проверки; 23 targeted PG tests, Ruff/mypy passed. Последний remote result пока ожидается; прежний анализ выше сохраняется как история, resolved старые inline-тексты не считаются новыми failed rules.

Окончательный результат 2026-10-03T21:22:54.861387+03:00: [CI37143596385](https://github.com/alxprgstech/sso/actions/runs/37143596385) и [CodeScene7799341](https://codescene.io/projects/85555/delta/results/7799341) для 8b3e958 **success**, все8 внутренних CI jobs и все3 quality gates passed. Все блокирующие причины этого анализа устранены; suppression/ослабления защиты/тестов не было. Детали проверок — в [acceptance](../acceptance.md).
