#!/usr/bin/env bash
# Prepare the private Codex credential mount and start ChatGPT device login.
set -Eeuo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# shellcheck source=lib.sh
. "$ROOT_DIR/scripts/lib.sh"

ENV_FILE=${ENV_FILE:-$ROOT_DIR/.env}
[[ -f $ENV_FILE ]] || die "Missing $ENV_FILE. Run ./install.sh or create it from .env.example first."
export ENV_FILE

AI_PROVIDER=$(env_get "$ENV_FILE" AI_PROVIDER)
[[ $AI_PROVIDER == codex ]] || die "Set AI_PROVIDER=codex in $ENV_FILE before signing in."

PUID_VALUE=$(env_get "$ENV_FILE" PUID)
PGID_VALUE=$(env_get "$ENV_FILE" PGID)
PUID_VALUE=${PUID_VALUE:-$(id -u)}
PGID_VALUE=${PGID_VALUE:-$(id -g)}
[[ $PUID_VALUE =~ ^[0-9]+$ ]] || die "PUID must be a numeric user id."
[[ $PGID_VALUE =~ ^[0-9]+$ ]] || die "PGID must be a numeric group id."

CODEX_AUTH_DIR=$(env_get "$ENV_FILE" CODEX_AUTH_DIR)
CODEX_AUTH_DIR=${CODEX_AUTH_DIR:-$ROOT_DIR/.codex-auth}
if [[ $CODEX_AUTH_DIR != /* ]]; then
  CODEX_AUTH_DIR="$ROOT_DIR/$CODEX_AUTH_DIR"
fi

if ! mkdir -p "$CODEX_AUTH_DIR" 2>/dev/null; then
  need_sudo
  "${SUDO[@]}" mkdir -p "$CODEX_AUTH_DIR"
fi
if [[ $(stat -c '%u:%g' "$CODEX_AUTH_DIR" 2>/dev/null || true) != "$PUID_VALUE:$PGID_VALUE" ]]; then
  need_sudo
  "${SUDO[@]}" chown -R "$PUID_VALUE:$PGID_VALUE" "$CODEX_AUTH_DIR"
  "${SUDO[@]}" chmod 700 "$CODEX_AUTH_DIR"
else
  chmod 700 "$CODEX_AUTH_DIR"
fi

COMPOSE=(docker compose --env-file "$ENV_FILE")
"${COMPOSE[@]}" build worker
"${COMPOSE[@]}" run --rm --no-deps --entrypoint sh worker -c \
  'mkdir -p /codex/log && test -w /codex && test -w /codex/log' \
  || die "The worker cannot write to /codex. Check PUID, PGID, and CODEX_AUTH_DIR in $ENV_FILE."

say "Open the displayed URL, approve a new one-time code, and keep this command running until Codex confirms the login."
"${COMPOSE[@]}" run --rm --no-deps worker codex login --device-auth
[[ -f $CODEX_AUTH_DIR/auth.json ]] || die "Codex login did not create $CODEX_AUTH_DIR/auth.json."
if [[ $(stat -c '%u' "$CODEX_AUTH_DIR/auth.json") == "$(id -u)" ]]; then
  chmod 600 "$CODEX_AUTH_DIR/auth.json"
else
  need_sudo
  "${SUDO[@]}" chmod 600 "$CODEX_AUTH_DIR/auth.json"
fi
say "Codex login was saved successfully."
