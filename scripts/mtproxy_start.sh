#!/usr/bin/env bash
set -euo pipefail

SECRETS_FILE="${MTPROXY_SECRETS_FILE:-/storage/tgunlock_robot/data/mtproxy_secrets.txt}"
PORT="${MTPROXY_PORT:-9443}"
ARGS=()

if [[ -f "$SECRETS_FILE" ]]; then
  while IFS= read -r secret; do
    secret="$(echo -n "$secret" | tr -d '[:space:]')"
    [[ -z "$secret" ]] && continue
    ARGS+=("-S" "$secret")
  done < "$SECRETS_FILE"
fi

exec /opt/MTProxy/objs/bin/mtproto-proxy -u nobody -p 8888 -H "$PORT" "${ARGS[@]}" --aes-pwd /opt/MTProxy/proxy-secret /opt/MTProxy/proxy-multi.conf -M 1
