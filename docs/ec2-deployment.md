# Развёртывание SSO на EC2

Обозначение ALXPRGS.SSO.OPS-EC2-01; DEPLOY-EC2-01; решение владельца 25.10.2026.
Дополнение к [руководству системного программиста](05-system-programmer-guide.md).
Предназначено для пустого выделенного Ubuntu 26.04 amd64: 2 vCPU, 2 ГБ RAM, 80 ГБ диска.
Публичная приёмка выполняется владельцем; наличие этих файлов не подтверждает работающий production.

## 1. Подготовка владельцем

- В Cloudflare: A `auth` → `54.152.17.1`, **DNS only**. Не оставляйте AAAA на другой сервер.
- Доступность TCP 80/443 нужна для HTTP-01 и сайта, SSH — владельцу и GitHub runner.
  Скрипты не меняют Security Groups, UFW, DNS и настройки SSH.
- В Resend домен уже подтверждён; отправитель `sso@alxprgs.tech`. Отключите open/click tracking
  для authentication-писем. API-ключ вводится на сервере, не в чат и не в репозиторий.
- Получите текущую проверенную ревизию проекта на рабочем компьютере. До публикации изменений
  в main автоматического деплоя новой реализации нет. Закрытый исходный код не публикуется.

Сначала настройте сервер, затем GitHub, затем переносите согласованные изменения в main.
Каждый успешный push-CI в main запускает CD; релиз/тег для этого не нужен.

## 2. Первоначальная установка

В PowerShell из корня checkout скопируйте только установщик и оператор на EC2. `ubuntu` —
предположение о пользователе стандартного AMI; замените, если ваш SSH-пользователь другой:

```powershell
scp -i "C:\path\ec2.pem" deploy/ec2/bootstrap.sh deploy/ec2/ssoctl.py ubuntu@54.152.17.1:~/
ssh -i "C:\path\ec2.pem" ubuntu@54.152.17.1
```

На сервере:

```bash
sudo bash ~/bootstrap.sh
```

Установщик использует официальный apt-репозиторий Docker, Ubuntu nginx/Certbot/Python/OpenSSL,
запрашивает Resend API key скрытым вводом и получает сертификат Let’s Encrypt через HTTP-01.
Выпуск означает согласие с условиями Let’s Encrypt; контакт — `alxprgs@gmail.com`.
Если DNS/порт 80 недоступен, исправьте их и повторите **ту же команду**.
Существующий `/etc/alxprgs-sso/runtime.env` сохраняется, ключи и volume не заменяются.
На время первой установки HTTP отвечает 503, кроме ACME challenge. HTTPS включается при первом деплое.

### 2.1. MFA в новой и существующей конфигурации

Новая установка `ssoctl configure` получает `FEATURE_TOTP_ENABLED=true`, `FEATURE_PASSKEY_ENABLED=true`, `FEATURE_RECOVERY_CODES_ENABLED=true`, `REQUIRE_ADMIN_MFA=true`. Существующий `runtime.env` не перезаписывается. Проверьте фактические значения:

```bash
sudo ssoctl mfa-status
```

Статус `absent (code default)` означает, что после обновления backend применится `true`. Явные `false` сохранятся. Для безопасного targeted изменения (только четыре ключа, private backup рядом, без перезапуска и без изменения секретов):

```bash
sudo ssoctl enable-mfa
```

Не перезаписывайте `runtime.env` целиком и не перегенерируйте ключи. Перед деплоем проверьте существующих администраторов и их факторы (`sudo ssoctl admin-status`); после миграции `0016_session_assurance` все старые сессии non-assured, поэтому каждый администратор пройдёт onboarding в `/admin`: настройка TOTP/Passkey → fresh подтверждение → admin. Обычные пользователи без фактора продолжают парольный вход. Проверьте `/api/v1/auth/capabilities`: все три MFA-флага и `admin_mfa_required` должны быть `true`. Если администратор утратил все факторы и recovery codes, используйте `sudo ssoctl recover-admin --username ADMIN --reason lost_factor --confirm ADMIN`: команда удаляет факторы, отзывает sessions/grants и пишет audit, но не создаёт assurance. Полный порядок, backup/rollback — [operations](operations.md#211-контролируемое-включение-mfa-на-существующем-сервере) и [ADR-0032](adr/0032-default-on-mfa-and-admin-policy.md). Production изменяет только владелец после отдельного разрешения.

```bash
sudo ssoctl test-alert
```

Проверьте получение уведомления на `alxprgs@gmail.com`. Ответ API означает приём Resend,
но не подтверждает доставку. При ошибке bootstrap не удаляйте конфигурацию ради повторной генерации.

## 3. Доступ GitHub Actions

На своём компьютере создайте **отдельную** SSH-пару для деплоя:

```powershell
ssh-keygen -t ed25519 -f "$HOME\.ssh\sso-deploy" -C "sso-github-deploy"
```

Для неинтерактивного runner нужен ключ без passphrase. Публичную строку из `sso-deploy.pub`
добавьте через уже имеющуюся административную SSH-сессию:

```bash
sudo -u ssodeploy nano /home/ssodeploy/.ssh/authorized_keys
```

Перед ключом используйте `restrict ` (один пробел между опцией и `ssh-ed25519`).
Пользователь не входит в docker group; sudo разрешает только `ssoctl deploy ...`.
Доставка приложения остаётся привилегированным доступом: Docker-образ и миграции выполняют
доверенный код main. Защитите main и доступ к секретам GitHub.

Получите fingerprint сервера по доверенной административной сессии:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

Сформируйте строку known_hosts как `54.152.17.1 ssh-ed25519 <публичный-ключ-хоста>`.
Для нестандартного порта — `[54.152.17.1]:PORT ...`. Не доверяйте результату `ssh-keyscan`
без сравнения fingerprint. Приватный **host key** не нужен.

Создайте GitHub Environment **production**, разрешив развёртывание из main. Для полностью
автоматических обновлений не включайте обязательное ручное approval. В этом Environment:

| Тип | Имя | Значение |
| --- | --- | --- |
| Variable | `SSH_HOST` | `54.152.17.1` |
| Variable | `SSH_PORT` | `22` или ваш порт |
| Secret | `SSH_PRIVATE_KEY` | Содержимое отдельного `sso-deploy` |
| Secret | `SSH_KNOWN_HOSTS` | Проверенная строка ключа хоста |

Resend API key, пароли БД, RSA и TOTP key в GitHub не передаются.

## 4. Первый деплой и администратор

После переноса изменений в main дождитесь **CI**, затем **Deploy SSO to EC2**.
Автоматический запуск реагирует только на успешный push-CI своего репозитория для main и собирает его точный SHA.
Перед сборкой и отправкой сверяется актуальный main; устаревшие ревизии пропускаются.

Для ручного тестового развёртывания без успешного общего CI: GitHub → Actions →
**Deploy SSO to EC2** → **Run workflow** → ветка **main** → **Run workflow**.
Workflow должен уже находиться в main, а Environment production и SSH secrets — быть настроены.
Ручной путь берёт точный SHA выбранного main; другие ветки не допускаются. Общий CI не
ожидается и не объявляется успешным. Сборка, проверка transport на PostgreSQL, freshness,
SSH host key, блокировка обновлений, backup и политика rollback остаются обязательными.
Если обязательная проверка transport упадёт, установка на EC2 не начнётся.
Образы amd64 собираются на runner; backend и закреплённый PostgreSQL доставляются архивом,
статический frontend извлекается из его образа. Registry не нужен.

Идентичность образов: раннеры CD/CI принудительно переключают Docker на классический image store
(`containerd-snapshotter=false`). **Docker 29 в свежих установках по умолчанию включает containerd
image store** (ID образов = digest манифеста, а не config-digest), поэтому EC2 тоже должен работать
на классическом store — `bootstrap.sh` закрепляет это в `/etc/docker/daemon.json`; уже установленный
сервер переводится однократно командой из раздела 5. Иначе после `docker load` образы получают
другие ID, и деплой упадёт на проверке image ID. PostgreSQL помечается тегом
`alxprgs-sso-postgres:<префикс digest>`, поэтому переживает load под именем.
Значения `backend_image`/`postgres_image` в manifest.json вычисляются из самого `images.tar`
(config-digest каждого образа), а не из `docker image inspect` демона раннера; неожиданный формат
или набор образов в архиве — жёсткая ошибка сборки бандла на runner.

На EC2:

```bash
sudo ssoctl status
sudo ssoctl admin
```

В интерактивном мастере задайте администратора и выберите **open** для самостоятельной регистрации.
Пароль вводится скрыто. До мастера публичная самостоятельная регистрация не считается настроенной.
Повторный мастер не заменяет существующего администратора. Откройте
`https://auth.alxprgs.tech`, проверьте вход администратора, затем регистрацию отдельного обычного
пользователя и подтверждение письмом в том же браузере. Не публикуйте ссылки/коды из писем.

TOTP, Passkey, Recovery codes остаются false. Подтверждение email новой регистрации обязательно.

### Идемпотентный повтор CD

Workflow различает `deployed`, `already_deployed`, `superseded` и ошибку. Перед тяжёлой
сборкой job `preflight` сверяет актуальность main и состояние установленного приложения.
Проверка идёт только на фиксированный `https://auth.alxprgs.tech` с доверенным TLS,
запретом redirects/proxy, timeout 15 секунд и лимитом ответа 4096 байт. Backend
`/health/identity` должен вернуть HTTP 200, готовую БД и полный commit SHA; frontend
`/build-info.json` — тот же SHA. Оба ответа обязаны иметь `Cache-Control: no-store`.
При совпадении build, verify, transport, SSH и install не выполняются, итог —
`already_deployed`. Если identity отсутствует (старая установка), SHA другой, ответ
повреждён, сервис/БД недоступны или ответ кэшируемый, выполняется обычный защищённый
deploy с конкретной безопасной причиной. Неверный TLS-сертификат, redirect или чужой
origin — ошибка безопасности, а не повод считать приложение отсутствующим.

Независимо от preflight `ssoctl deploy` под существующей flock-блокировкой повторно
проверяет установку перед первым побочным эффектом: `deployed.json`,
`current/manifest.json`, published frontend `build-info.json`, отсутствие maintenance,
running backend container с ожидаемым image ID/config_files и локальный
`/health/identity`. Только согласованное состояние даёт no-op без распаковки,
`docker load`, backup, миграций, перезапуска, переключения `current`, reload nginx и
уведомления. `highwater.json` по-прежнему защищает sequence, но не считается
доказательством успешной установки.

Результат серверной команды передаётся в workflow строгой строкой
`ssoctl-result:{"version":1,...}` через `scripts/deploy_result.py`; человекочитаемый
вывод не парсится. `installed=true` допустим только для фактической установки.
Если на сервере ещё старый `ssoctl` без протокола, workflow помечает результат
`deployed_legacy` и предупреждает, что серверная no-op защита не активна; установка
при этом выполняется прежним проверенным путём. Первый переход описан в разделе 5.

### Повтор отдельных стадий CD

Workflow состоит из jobs `preflight` → `build` → `verify` → `deploy` → `public-check`
и финального `report`. `preflight` проверяет freshness main и, если SHA уже установлен
и исправен, завершает run как `already_deployed`, пропуская остальные стадии.
`build` собирает transport и сохраняет его как приватный Actions artifact на 7 дней.
`verify` проверяет этот архив на PostgreSQL; `deploy` скачивает тот же неизменяемый
artifact текущего run. Имя содержит run ID и номер попытки build, передаётся через
outputs; повтор deploy использует сохранённое имя успешного build. Секреты production
доступны только job `deploy`.

Последний внешний job `public-check` выполняет запрос с GitHub runner к
`https://auth.alxprgs.tech/health/ready`: проверяет DNS/соединение, доверенный TLS,
HTTP 200 и JSON `{"status":"ready","database":"connected"}`. Таймаут запроса — 15 секунд;
редиректы и повторные попытки не допускаются. Недоступность домена, ошибка сертификата,
maintenance, HTML вместо JSON или неготовая БД делают workflow красным. Проверка
запускается после фактической установки, после серверного `already_deployed`, а также
после раннего `already_deployed`; при пропуске устаревшего SHA она пропускается.
Она дополняет проверки на EC2 и не выполняет rollback уже установленного приложения.

При внешней ошибке откройте исходный запуск → **Re-run jobs → Re-run failed jobs**.
Если упал `deploy`, повторятся доставка и серверная установка без сборки и проверки
успешного transport. Если упал `verify`, повторятся проверка и зависимый `deploy`.
Если упал только `public-check`, повторится только внешний запрос, без сборки и установки.
Если повторный preflight подтвердит тот же исправно установленный SHA, серверная
установка не выполняется; ранний no-op не пересобирает и не отправляет transport.
Серверная установка повторяется целиком: проверки, backup, миграции и readiness;
продолжения с произвольной команды внутри миграции нет. Номер run/SHA остаётся прежним.

**Re-run all jobs** пересобирает приложение; новая попытка build создаёт отдельный artifact.
Удалённый/просроченный artifact приводит к отказу скачивания: выполните полный повтор
актуального run. Если изменился код, нужен новый запуск для нового SHA, а не повтор старого.
Если main продвинулся, старый deploy пропускается; сервер также отвергает устаревший
номер run. Эти ограничения не обходятся повтором job.

## 5. Обновление и ошибки

Если `sudo docker info --format '{{.Driver}}'` показывает `overlayfs`, сервер работает на containerd
image store (умолчание Docker 29) и деплой образов упадёт на проверке image ID. Однократно
переведите демон на классический store (остальные ключи daemon.json сохраняются):

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path
path = Path("/etc/docker/daemon.json")
config = json.loads(path.read_text()) if path.exists() else {}
config.setdefault("features", {})["containerd-snapshotter"] = False
path.write_text(json.dumps(config, indent=2))
PY
sudo systemctl restart docker
sudo docker info --format '{{.Driver}}'   # ожидается overlay2
```

Следующие push в main обновляются автоматически после CI. Во время обновления nginx показывает
503 с техническим обслуживанием. Порядок: блокировка оператора → проверка bundle/SHA/image ID
и свободного места → остановка backend → backup → миграции → backend readiness → HTTPS/discovery.
Первичная пустая БД создаётся и мигрируется без предшествующего backup несуществующих таблиц.

Номер CD workflow сохраняется на сервере до изменений. Старший уже принятый номер нельзя
заменить младшим даже после неудачи. Повтор **того же run/SHA** разрешён; используйте Re-run jobs
после исправления внешней причины. Не обнуляйте `highwater.json` для обхода защиты.
Не переименовывайте/не создавайте заново workflow без отдельной процедуры смены счётчика.

Если backup не получился, миграции не запускаются, прежний backend возобновляется при доступной
неизменной схеме. После попытки миграции автоматический rollback допустим только при одинаковом
fingerprint комплекта миграций и совпадении фактической ревизии БД. Иначе backend останавливается,
сайт остаётся в maintenance, workflow красный. БД автоматически **никогда** не восстанавливается.
Неуспешная новая установка также остаётся закрытой до исправления и повторного запуска.

```bash
sudo ssoctl status
sudo journalctl -u alxprgs-sso-backup.service -u alxprgs-sso-renew.service --since today
sudo nginx -t
sudo docker ps --format 'table {{.Names}}\t{{.Status}}'
sudo systemctl list-timers 'alxprgs-sso-*'
```

Вывод ошибок намеренно краткий: сообщение называет имя и argv неуспешной команды (например,
`docker failed (docker image inspect sha256:…)`), но stderr дочерних команд не выводится.
При ошибке миграции имя сохранённого
контейнера выводится оператором; смотрите его `docker logs` приватно. Успешный migration-контейнер
удаляется. Не присылайте необработанные `docker inspect`,
`docker compose config`, environment или журналы с персональными данными.
Установленный root-оператор обновляйте командой `ssoctl self-update`; полный bootstrap
ради одного скрипта не запускайте: он затрагивает пакеты, сертификаты и сервисы.
Self-update меняет только `/opt/alxprgs-sso/tools/ssoctl.py` и не обновляет приложение.

### Обновление установленного ssoctl

Оператор и приложение обновляются независимо. `ssoctl self-update` не требует
работающего приложения, текущего release, доступного backend или `runtime.env` и не
выполняет bootstrap, deploy, миграции, перезапуск сервисов и отправку писем.

#### Первый переход (один раз, вручную)

Установленная версия может не содержать self-update и содержать дефект argparse,
поэтому первый файл заменяется вручную; после этого доступны обе формы команды.

1. После merge выберите полный SHA main, прошедший review и обязательный CI. На рабочей
   станции получите файл именно этой ревизии, а не из ветки или рабочего дерева:
   ```bash
   git fetch origin main
   git cat-file -e <MERGED_SHA>:deploy/ec2/ssoctl.py
   git show <MERGED_SHA>:deploy/ec2/ssoctl.py > ssoctl-first-transition.py
   sha256sum ssoctl-first-transition.py
   ```
   Сверьте SHA-256 с review/CI. Не используйте сокращённый SHA, тег или локальные
   незакоммиченные изменения.
2. Скопируйте **только** оператор в домашний каталог администратора:
   `scp -i <key> ssoctl-first-transition.py ubuntu@54.152.17.1:~/`.
3. В административной SSH-сессии сохраните текущий файл и проверьте кандидата до
   установки (от обычного пользователя, без sudo, конфигурации, сети и Docker):
   ```bash
   sudo cp -p /opt/alxprgs-sso/tools/ssoctl.py /opt/alxprgs-sso/tools/ssoctl.py.pre-self-update
   /usr/bin/python3 ~/ssoctl-first-transition.py --help >/dev/null
   /usr/bin/python3 ~/ssoctl-first-transition.py recover-admin --help >/dev/null
   /usr/bin/python3 ~/ssoctl-first-transition.py self-update --help >/dev/null
   ```
4. Установите файл с ожидаемыми owner/mode и проверьте установленную копию:
   ```bash
   sudo install -o root -g root -m 0755 ~/ssoctl-first-transition.py /opt/alxprgs-sso/tools/ssoctl.py
   sudo /usr/local/sbin/ssoctl --help >/dev/null
   sudo /usr/local/sbin/ssoctl self-update --help >/dev/null
   sudo ssoctl status
   ```
5. `runtime.env`, ключи, `/etc/sudoers.d/alxprgs-sso`, wrapper `/usr/local/sbin/ssoctl`,
   Docker volumes, releases, `deployed.json`, `highwater.json`, `current`, maintenance,
   GitHub secrets и сервисы не меняются. Полный bootstrap не запускается.
6. При ошибке верните прежний файл и проверьте его:
   ```bash
   sudo install -o root -g root -m 0755 /opt/alxprgs-sso/tools/ssoctl.py.pre-self-update /opt/alxprgs-sso/tools/ssoctl.py
   sudo ssoctl status
   ```
7. После успешной замены настройте read-only GitHub-доступ и проверьте переход:
   ```bash
   sudo ssoctl self-update --sha <MERGED_SHA>
   ```
   Ожидается `already current` для установленного SHA. Затем `sudo ssoctl self-update`
   обновляет до актуального main. Сохранение прежнего CD-поведения проверяется отдельным
   повторным CD run: для уже установленного SHA ожидается `already_deployed` без
   серверных побочных эффектов.

#### Первоначальная настройка read-only GitHub-доступа

GitHub-токен — отдельный read-only credential, не Resend/application credential и не
deploy SSH key. Создайте fine-grained personal access token: GitHub → Settings →
Developer settings → Personal access tokens → Fine-grained tokens. Resource owner —
`alxprgstech`, Repository access — **Only select repositories** → `sso`, Repository
permissions — **Contents: Read-only** (обязательный `Metadata: Read-only` добавляется
автоматически). Другие permissions не нужны. Срок действия — не более 90 дней.

На сервере сохраните токен скрытым вводом в root-owned файл вне репозитория и
`runtime.env`:
```bash
sudo bash -c 'umask 077; read -rsp "GitHub read-only token: " T; printf "%s" "$T" > /etc/alxprgs-sso/github-read.token; unset T; echo'
sudo chown root:root /etc/alxprgs-sso/github-read.token
sudo chmod 0600 /etc/alxprgs-sso/github-read.token
```
Оператор отказывается работать, если файл является symlink, не root-owned или доступен
группе/другим. Токен не передаётся в argv/URL, не выводится и не логируется. Для
ротации замените файл той же командой; перезапуск сервисов не нужен. Проверка
доступа — `sudo ssoctl self-update` (при совпадении содержимого это безопасный no-op).

#### Регулярные обновления

```bash
sudo ssoctl self-update
sudo ssoctl self-update --sha <FULL_40_HEX_MAIN_SHA>
```

Без `--sha` main один раз разрешается в полный commit SHA, и файл загружается именно
этой ревизии; последующее продвижение main не смешивает metadata и содержимое. С `--sha`
принимается только полный 40-символьный lowercase hex, принадлежащий истории main;
ветки, теги, сокращённые SHA и коммиты PR-веток отклоняются.

Обе формы печатают выбранный commit SHA, результат `updated`/`already current` и путь
backup при замене. Если содержимое уже совпадает, команда успешно завершается без
замены и без лишней резервной копии. Перед заменой кандидат проверяется на синтаксис,
`--help` целевым `/usr/bin/python3` с timeout и наличие обязательных команд, включая
`recover-admin` и `self-update`; один `compile` не считается достаточной проверкой.
Резервная копия действующего файла создаётся в `/var/lib/alxprgs-sso/operator-backups`
(root-only, `0600`, уникальное имя без перезаписи), затем файл атомарно заменяется под
общей flock-блокировкой и проверяется. При ошибке проверки прежний файл восстанавливается
автоматически, backup сохраняется. Одновременно выполняется не более одной операции
оператора; другой self-update/deploy/backup/renew ждёт блокировку.

#### Ошибки и ручной откат

- Нет токена или неверные owner/mode — отказ до сети, установленный файл не меняется.
- HTTP 401/403 — токен истёк, отозван или не имеет `Contents: Read-only`; замените его,
  файл не меняется.
- HTTP 404, неверный TLS, redirect, timeout, обрыв или превышение лимитов — отказ,
  файл не меняется.
- SHA отсутствует в истории main или имеет неверный формат — отказ до загрузки файла.
- Пустой файл, синтаксическая ошибка, конфликт argparse или отсутствие обязательного
  интерфейса — отказ до backup и замены.
- Приложение остановлено, БД недоступна или release отсутствует — обновление оператора
  всё равно выполняется.

Ручной откат не зависит от работающей команды self-update. Выберите backup и установите
его с теми же owner/mode:
```bash
sudo ls -l /var/lib/alxprgs-sso/operator-backups
sudo install -o root -g root -m 0755 /var/lib/alxprgs-sso/operator-backups/<FILE>.bak /opt/alxprgs-sso/tools/ssoctl.py
sudo /usr/local/sbin/ssoctl --help >/dev/null
sudo ssoctl status
```
Обновление оператора не обновляет приложение, его версию, контейнеры, БД или nginx и
не является заменой CD. Для отката приложения используйте существующие release/backup
процедуры; полный bootstrap ради отката одного скрипта не нужен.

## 6. Backup, сертификаты и секреты

Копии: `/var/lib/alxprgs-sso/backups`, только root; ежедневно около 03:00 UTC и перед обновлением.
Backup timer включается после первого успешного деплоя. Сертификат проверяется дважды в день;
Certbot продлевает его при необходимости и перезагружает nginx. Ошибка renewal или остаток срока
менее 14 дней — failure с уведомлением. Выполните проверку staging ACME:

```bash
sudo certbot renew --cert-name auth.alxprgs.tech --dry-run
sudo systemctl start alxprgs-sso-backup.service
sudo systemctl start alxprgs-sso-renew.service
sudo ssoctl test-alert
sudo find /var/lib/alxprgs-sso/backups -maxdepth 1 -type f -printf '%f %s bytes\n'
```

Хранение — 30 дней; перед проверкой доступности БД оператор запускает штатную очистку собственных
просроченных копий. SHA-256 успешных dump хранится в root-only `backup-checksums.json`.
Проверка перед восстановлением: `sudo ssoctl verify-backup SELECTED_BACKUP.sql`, где имя заменено
на реальное из каталога копий. Подменённый dump или отсутствующая контрольная сумма дают отказ.
Снапшот deletion journal рядом с dump **не заменяет свежий журнал перед восстановлением**.
При отказе Resend уведомление не доставляется, ошибка остаётся в systemd/GitHub.
Локальные копии не защищают от потери EBS/EC2. Сохраните отдельно защищённую копию
`/etc/alxprgs-sso/runtime.env` и сертификатов; не кладите её в Git или Actions artifacts.

Для замены Resend key отредактируйте `sudoedit /etc/alxprgs-sso/runtime.env`, сохраняя формат
`NAME="JSON-escaped value"`. RSA PEM занимает одну строку с `\n`; символ `$` записывается как `$$`.
Не меняйте пароли уже инициализированной БД простой правкой env. После смены почтового ключа
повторите актуальный CD run, затем `sudo ssoctl test-alert` и регистрацию.
Ротация RSA/TOTP/паролей — отдельные процедуры [эксплуатации](operations.md).

Старые образы/каталоги релизов автоматически не удаляются: они нужны для rollback.
Контролируйте `df -h` и `sudo docker system df`; при недостатке места обновление прекращается.
Не используйте `docker system prune --volumes` и не удаляйте `alxprgs-sso-data`.

## 7. Ручное восстановление

Сначала изучите [миграции](migration.md) и [правила восстановления](operations.md).
При несовместимой миграции предпочтителен исправляющий push; возврат кода без анализа схемы запрещён.
Для восстановления dump в maintenance остановите всех писателей, экспортируйте **свежий** deletion
journal из актуальной БД и только затем применяйте dump с overlay в одной транзакции.
Если актуальная БД потеряна и свежий журнал получить нельзя, штатное восстановление заблокировано;
нельзя подставлять старый journal или менять время ради обхода проверки.

Команды выполняются root в SSH-сессии. Текущий каталог релиза разрешается только через root-ссылку:

```bash
sudo -i
ssoctl maintenance
cd /opt/alxprgs-sso/current
# Установите SSO_BACKEND_IMAGE из backend_image manifest.json, без вывода секретов:
export SSO_BACKEND_IMAGE=$(python3 -c 'import json; print(json.load(open("manifest.json"))["backend_image"])')
export SSO_POSTGRES_IMAGE=$(python3 -c 'import json; print(json.load(open("manifest.json"))["postgres_image"])')
```

Для команд Compose значение `SSO_BACKEND_IMAGE` нужно установить **до** вызова Compose;
ниже приведён полный экспорт свежего журнала через проверенный db-контейнер:

```bash
db=$(docker compose --project-name alxprgs-sso --env-file /etc/alxprgs-sso/runtime.env -f compose.yml ps -q db)
umask 077
python3 - "$db" <<'PY'
import subprocess, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from privacy_journal import EXPORT_SQL
result = subprocess.run(['docker', 'exec', sys.argv[1], 'psql', '-XAt', '-v', 'ON_ERROR_STOP=1',
                         '-U', 'sso_owner', '-d', 'sso_db', '-c', EXPORT_SQL],
                        check=True, capture_output=True)
Path('/var/lib/alxprgs-sso/fresh-journal.json').write_bytes(result.stdout)
PY
python3 scripts/restore_db.py /var/lib/alxprgs-sso/backups/SELECTED_BACKUP.sql \
  --confirm --docker --container "$db" --user sso_owner --db sso_db \
  --deletion-journal /var/lib/alxprgs-sso/fresh-journal.json
```

`SELECTED_BACKUP.sql` — выбранный оператором и проверенный по SHA-256 dump; не запускайте пример
буквально. Используйте приложение/ключи, совместимые со схемой восстановленного dump; выбор
предыдущего root-каталога релиза и смена `current` требуют анализа миграции. После проверки:

```bash
ssoctl resume
exit
```

`resume` проверяет readiness и HTTPS; при ошибке сохраняет maintenance. Он не мигрирует БД.
После восстановления проверьте отсутствие удалённых субъектов, вход, регистрацию и backup.

## 8. Приёмка с владельцем

В [приёмке](acceptance.md) записываются отдельно локальные результаты и факты с AWS:
первая установка, повтор bootstrap без смены ключей, HTTPS/issuer, обязательный email flow,
push-update с сохранением пользователя, backup/restore на отдельной синтетической БД,
dry-run сертификата, уведомление и отрицательные сценарии обновления.
Не испытывайте разрушительные сбои на единственной БД с реальными пользователями.

Источники: [Docker Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[Certbot webroot/renew](https://eff-certbot.readthedocs.io/en/stable/using.html),
[GitHub workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).

## Ошибка подготовки каталога на GitHub runner

Ошибка `ValueError: Output parent must already exist` в `scripts.check_ec2_runtime` означает,
что чистый runner не имел игнорируемой папки `artifacts`. Исправленная версия создаёт
родительскую папку сама, затем защищённый одноразовый каталог с проверкой прав.
На EC2 ничего создавать вручную не требуется. Перенесите исправление в main и запустите
новый **Run workflow**: **Re-run** старого запуска использует прежний SHA и не подхватит новый код.
