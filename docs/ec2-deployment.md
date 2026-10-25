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

## 5. Обновление и ошибки

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

Вывод ошибок намеренно краткий, без stderr дочерних команд. При ошибке миграции имя сохранённого
контейнера выводится оператором; смотрите его `docker logs` приватно. Успешный migration-контейнер
удаляется. Не присылайте необработанные `docker inspect`,
`docker compose config`, environment или журналы с персональными данными.
Установленный root-оператор обновляйте повторным запуском **проверенного** bootstrap при изменениях
самого `ssoctl.py`/bootstrap; обычный push обновляет приложение и production Compose/nginx.

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
