# Регламент версионирования, релизов и развёртывания ALXPRGS SSO

- Обозначение документа: ALXPRGS.SSO.REL-01
- Версия: 1.0.0
- Дата: 2026-09-24T11:40:00+03:00
- Статус: процесс описан; теговый dry-run и удалённый CI нынешнего дерева не проверены (GOAL-09)

---

## 1. Модель версионирования (VER-01, VER-02)

Система ALXPRGS SSO использует единое семантическое версионирование (**SemVer 2.0.0**) для всех входящих в состав компонентов:
- Сервер аутентификации (FastAPI Backend);
- Пользовательский интерфейс (React Frontend);
- Клиентская библиотека (Python SDK `alxprgs-sso`).

Единым источником истины для версии проекта является файл `VERSION` в корне репозитория.

### 1.1. Правила изменения версий
- **MAJOR** (`X.0.0`): Нарушение обратной совместимости API, кардинальные изменения модели данных, требующие несовместимых миграций БД, удаление или изменение существующих OIDC claims / scopes.
- **MINOR** (`0.X.0` или `X.Y.0`): Добавление новой обратно совместимой функциональности, расширение API, новые возможности SDK.
- **PATCH** (`X.Y.Z`): Обратно совместимые исправления ошибок и уязвимостей безопасности.
- **Prerelease** (`X.Y.Z-rc.N`): Кандидаты в релиз для внутреннего интеграционного тестирования.

### 1.2. Соответствие SemVer и Python PEP 440
В соответствии со стандартами упаковки Python (PEP 440), суффиксы предварительных релизов автоматически транслируются скриптом `scripts/bump_version.py`:
- `1.0.0-rc.1` $\to$ `1.0.0rc1`
- `1.0.0-alpha.1` $\to$ `1.0.0a1`
- `1.0.0-beta.2` $\to$ `1.0.0b2`

Git-теги формируются с префиксом `v`: `v0.1.0`, `v1.0.0-rc.1`.

---

## 2. Команда подготовки версии (VER-03)

Подготовка новой версии выполняется строго одной командой:

```bash
# Проверка согласованности версий всех компонентов
python scripts/bump_version.py check

# Повышение patch-версии (0.1.0 -> 0.1.1)
python scripts/bump_version.py bump patch

# Повышение minor-версии (0.1.0 -> 0.2.0)
python scripts/bump_version.py bump minor

# Выпуск release candidate (0.1.0 -> 0.1.0-rc.1)
python scripts/bump_version.py bump prerelease --rc 1

# Установка точной версии
python scripts/bump_version.py set 0.2.0
```

Скрипт автоматически обновляет:
1. `VERSION`
2. `backend/pyproject.toml`
3. `packages/python-sdk/pyproject.toml`
4. `frontend/package.json`
5. `CHANGELOG.md` (добавляет секцию новой версии с текущей датой).

*Примечание*: Данная команда не выполняет публикацию или развёртывание. Созданные изменения коммитятся в Git разработчиком.

---

## 3. Процесс непрерывной интеграции (CI-01, CI-02)

Пайплайн CI описан в `.github/workflows/ci.yml`:
- **Триггеры**: Push в ветку `main`, Pull Request в ветку `main`, ручной запуск `workflow_dispatch`.
- **Безопасность**:
  - Все сторонние Actions зафиксированы полным commit SHA (40 символов).
  - Минимальные права `permissions: contents: read`.
  - Отсутствие доступа PR к production-секретам.
  - Concurrency group с отменой устаревших прогонов (`cancel-in-progress: true`).
- **Состав проверок**:
  1. `lint-and-typecheck`: Ruff (линтер и форматтер Python), Mypy / Pyright, ESLint, TypeScript typecheck (`tsc --noEmit`).
  2. `backend-unit-and-integration`: запуск pytest с реальным сервисом PostgreSQL 16 в контейнере, применение миграций Alembic, тестирование гонок и атомарности.
  3. `mfa-feature-profiles`: тесты в профиле default-off (все 4 флага `false`, проверка 404 на API) и тесты в профиле enabled (`TEST_PROFILE=enabled`).
  4. `sdk-package`: сборка `sdist` и `wheel` пакета `alxprgs-sso`, установка в чистую виртуальную среду, тестирование примеров.
  5. `frontend-build`: сборка production-бандла Vite (`npm run build`).

---

## 4. Процесс выпуска релиза (REL-01..03)

Выпуск релиза автоматизирован через `.github/workflows/release.yml`:
1. **Запуск**: Выполняется владельцем репозитория вручную через `workflow_dispatch` с указанием существующего Git-тега (например, `v0.1.0`).
2. **Верификация коммита**:
   - Workflow разрешает тег в точный Commit SHA.
   - Проверяет принадлежность коммита ветке `main`.
   - Проверяет строгое совпадение версии в корневом `VERSION` с версией тега.
3. **Сборка артефактов**:
   - Backend и SDK wheel/sdist, архивы frontend и миграций, `MIGRATION.md`, `RELEASE_NOTES.md`, `release-manifest.json`, `SHA256SUMS.txt` в одном комплекте `dist/artifacts/`.
   - В именах prerelease Python-пакетов `-rc.N` переводится в PEP 440 `rcN`; продуктовая версия и frontend-архив сохраняют SemVer.
4. **Публикация Draft Release**:
   - Создается черновик релиза (Draft Release).
   - Загружаются все собранные артефакты и контрольные суммы.
   - После загрузки проверяются все имена и контрольные суммы; релиз остаётся **draft**. Публикация требует отдельного поручения владельца.
   - Права на запись (`contents: write`) изолированы исключительно в финальном шаге публикации.

Локальная проверка без публикации: `python scripts/build_release_artifacts.py build --outdir <пустая-директория>`, затем `python scripts/build_release_artifacts.py verify --outdir <та-же-директория>`. Она не заменяет теговый запуск: manifest dirty-дерева имеет `source_tree_dirty=true`. На 26.09.2026 нынешний код прошёл только такой нетегированный dry-run; удалённый workflow и полный PostgreSQL/browser CI не запускались. Границы доказательств — в [акте GOAL-09](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/acceptance-goal-09.md).

---

## 5. Временно отключённый контур CD и правила будущей активации (CD-01..03)

В соответствии с требованием безопасности CD-01:
- Шаблон развёртывания размещен в `deploy/github-actions/cd.yml.example` **вне** каталога `.github/workflows/`.
- **Все строки файла закомментированы символом `#`**.
- Никакие коммиты, теги или действия в CI/Release не инициируют автоматическое развёртывание.

### Инструкция будущей активации CD:
1. Выбрать и подготовить целевую инфраструктуру (серверы, Docker Swarm / Kubernetes / VPS).
2. Настроить в GitHub Secrets репозитория параметры окружения:
   - `PROD_HOST`, `PROD_SSH_KEY`, `PROD_DB_URL`, `PROD_JWT_PRIVATE_KEY`, `PROD_TOTP_KEY`.
3. Настроить в GitHub Environment защиту развёртывания (Required Reviewers).
4. Скопировать `deploy/github-actions/cd.yml.example` в `.github/workflows/cd.yml`.
5. Раскомментировать необходимые строки, зафиксировать Commit SHA и закоммитить изменения.

## Sentry release/source maps

`release_bundle.py build --private-maps <PRIVATE_DIR>` создаёт общую VERSION/full-SHA identity, hidden maps/Debug IDs, private JS/maps manifest и deploy archive без maps. Verifier сравнивает identity внутри backend wheel/frontend archive, а также точное совпадение JS с private bundle. Не пересобирайте frontend после upload. Private промежуточный artifact хранится один день и не входит в GitHub Release.

`prepare-sentry-release` зависит от build и блокирует draft при включённом неуспешном upload. Trusted workflow checkout и fixed CLI installation выполняются без token; единственный upload step получает protected `SENTRY_AUTH_TOKEN`. Требуются `SENTRY_ORG`, оба `SENTRY_PROJECT_*`, `SENTRY_URL=https://de.sentry.io/`, opt-in `SENTRY_RELEASE_UPLOAD_ENABLED`. Dry-run/upload-disabled всегда offline, даже если credentials присутствуют. Dirty/untagged local bundles не допускаются к upload. Runtime release override не используется. Build не создаёт deployment record; CD остаётся неактивным. Полный порядок: [observability.md](observability.md).

## Миграция следующего релиза: 0004_privacy

Новый контракт регистрации требует `terms_accepted=true`, `data_processing_consent=true` и актуальные `legal_versions` из публичного API. Обновите сторонние формы и API-клиенты вместе с frontend. Старые пользователи подтверждают документы после входа; новые SSO codes/tokens до этого не выдаются.

До запуска нового приложения выполните миграцию. Очистка старой геолокации/полного User-Agent необратима при downgrade; согласия и состояния удаления при downgrade теряются. Для отката восстанавливайте совместимую копию только со свежим журналом удалений и закрытым доступом (operations.md). Нельзя открывать старый backend поверх новой схемы как способ обхода consent/deletion gate. Версия и релиз этой задачей не выпускаются.
