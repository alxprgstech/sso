#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $SSH_HOST =~ ^[a-zA-Z0-9.-]+$ ]]
[[ $SSH_USER == ssodeploy ]]
[[ $SSH_PORT =~ ^[0-9]+$ && $SSH_PORT -ge 1 && $SSH_PORT -le 65535 ]]
[[ $DEPLOY_SHA =~ ^[a-f0-9]{40}$ ]]
[[ $DEPLOY_SEQUENCE =~ ^[1-9][0-9]*$ ]]
[[ $GITHUB_RUN_ID =~ ^[0-9]+$ && $GITHUB_RUN_ATTEMPT =~ ^[0-9]+$ ]]
test -s sso-ec2.tar.gz
test -n "$SSH_PRIVATE_KEY"
test -n "$SSH_KNOWN_HOSTS"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
private=$(mktemp -d)
remote="/home/ssodeploy/incoming/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
target="$SSH_USER@$SSH_HOST"
printf '%s\n' "$SSH_PRIVATE_KEY" > "$private/key"
printf '%s\n' "$SSH_KNOWN_HOSTS" > "$private/known_hosts"
unset SSH_PRIVATE_KEY SSH_KNOWN_HOSTS
opts=(-i "$private/key" -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$private/known_hosts" -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
cleanup() {
  # Only this run's fixed inbox path. Root-owned verified releases remain intact.
  ssh "${opts[@]}" -p "$SSH_PORT" "$target" "rm -f '$remote/sso-ec2.tar.gz'; rmdir '$remote'" || true
  rm -f "$private/key" "$private/known_hosts"
  rmdir "$private"
}
trap cleanup EXIT
ssh "${opts[@]}" -p "$SSH_PORT" "$target" "umask 077; mkdir '$remote'"
scp "${opts[@]}" -P "$SSH_PORT" sso-ec2.tar.gz "$target:$remote/sso-ec2.tar.gz"
# Capture the operator's machine protocol instead of reprinting server output.
set +e
output=$(ssh "${opts[@]}" -p "$SSH_PORT" "$target" \
  "sudo -n /usr/local/sbin/ssoctl deploy '$remote/sso-ec2.tar.gz' '$DEPLOY_SEQUENCE' '$DEPLOY_SHA'")
status=$?
set -e
if [[ $status -ne 0 ]]; then
  echo 'Server deployment command failed; inspect the sanitized operator error above.' >&2
  exit "$status"
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
printf '%s\n' "$output" | python3 "$root/scripts/deploy_result.py" \
  --sha "$DEPLOY_SHA" --sequence "$DEPLOY_SEQUENCE" --github-output "$GITHUB_OUTPUT"
