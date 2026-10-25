#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $EUID == 0 ]] || { echo 'Run with sudo bash deploy/ec2/bootstrap.sh'; exit 1; }
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 26.04 && $(dpkg --print-architecture) == amd64 ]] || {
  echo 'Expected Ubuntu 26.04 amd64'; exit 1;
}
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl nginx certbot python3 python3-cryptography openssl
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
    https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod 0644 /etc/apt/keyrings/docker.asc
  cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: resolute
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
docker compose version
systemctl enable --now docker nginx
id ssodeploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash ssodeploy
install -d -m 0700 -o ssodeploy -g ssodeploy /home/ssodeploy/.ssh /home/ssodeploy/incoming
touch /home/ssodeploy/.ssh/authorized_keys
chown ssodeploy:ssodeploy /home/ssodeploy/.ssh/authorized_keys
chmod 0600 /home/ssodeploy/.ssh/authorized_keys
install -d -m 0755 /opt/alxprgs-sso /opt/alxprgs-sso/tools /opt/alxprgs-sso/releases
install -d -m 0700 /etc/alxprgs-sso /var/lib/alxprgs-sso /var/lib/alxprgs-sso/backups
# nginx must traverse the state directory for the maintenance flag, but not list it.
chmod 0711 /var/lib/alxprgs-sso
install -m 0755 "$here/ssoctl.py" /opt/alxprgs-sso/tools/ssoctl.py
printf '#!/bin/sh\nexec /usr/bin/python3 /opt/alxprgs-sso/tools/ssoctl.py "$@"\n' > /usr/local/sbin/ssoctl
chmod 0755 /usr/local/sbin/ssoctl
printf 'ssodeploy ALL=(root) NOPASSWD: /usr/local/sbin/ssoctl deploy *\n' > /etc/sudoers.d/alxprgs-sso
chmod 0440 /etc/sudoers.d/alxprgs-sso
visudo -cf /etc/sudoers.d/alxprgs-sso
ssoctl configure
install -d -m 0755 /var/www/letsencrypt /var/www/alxprgs-sso
printf '<!doctype html><meta charset="utf-8"><title>SSO</title><h1>Техническое обслуживание</h1>' > /var/www/alxprgs-sso/maintenance.html
chmod 0644 /var/www/alxprgs-sso/maintenance.html
# This script owns only its site; refuse an unrelated default listener.
if [[ -L /etc/nginx/sites-enabled/default && $(readlink -f /etc/nginx/sites-enabled/default) == /etc/nginx/sites-available/default ]]; then
  unlink /etc/nginx/sites-enabled/default
fi
if [[ ! -f /etc/letsencrypt/live/auth.alxprgs.tech/fullchain.pem ]]; then
  cat > /etc/nginx/sites-available/alxprgs-sso <<'EOF'
server {
    listen 80;
    server_name auth.alxprgs.tech;
    access_log off;
    error_log /var/log/nginx/sso-error.log crit;
    location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 503; }
}
EOF
  chmod 0644 /etc/nginx/sites-available/alxprgs-sso
  ln -sfn /etc/nginx/sites-available/alxprgs-sso /etc/nginx/sites-enabled/alxprgs-sso
  nginx -t
  systemctl reload nginx
  certbot certonly --non-interactive --agree-tos --email alxprgs@gmail.com \
    --webroot -w /var/www/letsencrypt --cert-name auth.alxprgs.tech -d auth.alxprgs.tech
fi
# Renewal is owned by our timer so failures reach Resend.
systemctl disable --now certbot.timer 2>/dev/null || true
for task in backup renew; do
  cat > "/etc/systemd/system/alxprgs-sso-$task.service" <<EOF
[Unit]
Description=ALXPRGS SSO $task
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=oneshot
UMask=0077
ExecStart=/usr/local/sbin/ssoctl $task
EOF
done
cat > /etc/systemd/system/alxprgs-sso-backup.timer <<'EOF'
[Unit]
Description=Daily SSO backup
[Timer]
OnCalendar=*-*-* 03:00:00 UTC
Persistent=true
RandomizedDelaySec=10m
[Install]
WantedBy=timers.target
EOF
cat > /etc/systemd/system/alxprgs-sso-renew.timer <<'EOF'
[Unit]
Description=SSO certificate renewal
[Timer]
OnCalendar=*-*-* 00,12:00:00 UTC
Persistent=true
RandomizedDelaySec=30m
[Install]
WantedBy=timers.target
EOF
chmod 0644 /etc/systemd/system/alxprgs-sso-{backup,renew}.{service,timer}
systemctl daemon-reload
systemctl enable --now alxprgs-sso-renew.timer
echo 'Bootstrap ready. Add the deployment public key, configure GitHub, then deploy.'
echo 'Backup timer starts after the first successful deployment.'
