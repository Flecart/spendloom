#!/usr/bin/env bash
# Install or refresh Spendloom in this checked-out directory.
set -Eeuo pipefail
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=scripts/lib.sh
. "$ROOT_DIR/scripts/lib.sh"

[[ ${BASH_VERSINFO[0]} -ge 4 ]] || die "Bash 4 or newer is required."
detect_platform
say "Installing Spendloom for $DISTRO_ID ($ARCH) in $ROOT_DIR"
ensure_docker

ENV_FILE="$ROOT_DIR/.env"
if [[ -f $ENV_FILE ]]; then
  if [[ ${SPENDLOOM_NONINTERACTIVE:-0} != 1 ]] && ! confirm "Keep the existing .env and update only prompted values?"; then
    cp -p "$ENV_FILE" "$ROOT_DIR/.env.before-install.$(date +%Y%m%dT%H%M%S)"
    : > "$ENV_FILE"
  fi
else
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

ask() {
  local key=${1:?key} prompt=${2:?prompt} default=${3-} secret=${4:-0} answer
  answer=${!key:-$(env_get "$ENV_FILE" "$key")}
  if [[ ${SPENDLOOM_NONINTERACTIVE:-0} == 1 ]]; then printf '%s' "${answer:-$default}"; return; fi
  if [[ $secret == 1 ]]; then read -r -s -p "$prompt${answer:+ [kept]}: " answer; printf '\n' >&2
  else read -r -p "$prompt [${answer:-$default}]: " answer
  fi
  printf '%s' "${answer:-$default}"
}

APP_PASSWORD=$(ask APP_PASSWORD "Spendloom app password" "" 1)
[[ ${#APP_PASSWORD} -ge 12 ]] || die "APP_PASSWORD must be at least 12 characters."
SESSION_SECRET=$(env_get "$ENV_FILE" SESSION_SECRET); SESSION_SECRET=${SESSION_SECRET:-$(random_secret)}
AI_PROVIDER=$(ask AI_PROVIDER "AI provider (openai, anthropic, gemini)" "openai")
case $AI_PROVIDER in openai|anthropic|gemini) ;; *) die "AI_PROVIDER must be openai, anthropic, or gemini." ;; esac
AI_MODEL=$(ask AI_MODEL "Receipt AI model" "gpt-5.6-luna")
CHAT_MODEL=$(ask CHAT_MODEL "Optional chat model (blank reuses receipt model)" "")
API_KEY_NAME=$(tr '[:lower:]' '[:upper:]' <<<"$AI_PROVIDER")_API_KEY
AI_KEY=$(ask "$API_KEY_NAME" "$API_KEY_NAME (blank keeps receipt processing in manual review)" "" 1)
TELEGRAM_BOT_TOKEN=$(ask TELEGRAM_BOT_TOKEN "Optional Telegram bot token" "" 1)
PORT=$(ask SPENDLOOM_PORT "Local web port" "8080")
[[ $PORT =~ ^[0-9]{1,5}$ ]] && ((PORT > 0 && PORT < 65536)) || die "Port must be 1–65535."
if port_in_use "$PORT" && [[ -z $(docker compose -f "$ROOT_DIR/docker-compose.yml" ps -q web 2>/dev/null) ]]; then
  die "Port $PORT is already listening. Choose a free port before installing."
fi
APP_ORIGIN=$(ask APP_ORIGIN "Application origin (use a LAN URL only if intentional)" "http://localhost:$PORT")
PUID=$(ask PUID "Host user id" "$(id -u)")
PGID=$(ask PGID "Host group id" "$(id -g)")

env_set "$ENV_FILE" APP_PASSWORD "$APP_PASSWORD"
env_set "$ENV_FILE" SESSION_SECRET "$SESSION_SECRET"
env_set "$ENV_FILE" AI_PROVIDER "$AI_PROVIDER"
env_set "$ENV_FILE" AI_MODEL "$AI_MODEL"
env_set "$ENV_FILE" CHAT_MODEL "$CHAT_MODEL"
env_set "$ENV_FILE" "$API_KEY_NAME" "$AI_KEY"
env_set "$ENV_FILE" TELEGRAM_BOT_TOKEN "$TELEGRAM_BOT_TOKEN"
env_set "$ENV_FILE" APP_ORIGIN "$APP_ORIGIN"
env_set "$ENV_FILE" PUID "$PUID"
env_set "$ENV_FILE" PGID "$PGID"
chmod 600 "$ENV_FILE"

mkdir -p "$ROOT_DIR/data/backups"
if [[ -f $ROOT_DIR/data/receipt-ledger.db ]]; then
  cp -p "$ROOT_DIR/data/receipt-ledger.db" "$ROOT_DIR/data/backups/pre-install-$(date +%Y%m%dT%H%M%S)-receipt-ledger.db"
fi
if [[ $(stat -c '%u:%g' "$ROOT_DIR/data" 2>/dev/null || true) != "$PUID:$PGID" ]]; then
  need_sudo
  "${SUDO[@]}" chown -R "$PUID:$PGID" "$ROOT_DIR/data"
fi

COMPOSE=(docker compose --env-file "$ENV_FILE")
if [[ -n $TELEGRAM_BOT_TOKEN ]]; then
  "${COMPOSE[@]}" --profile telegram up -d --build
else
  "${COMPOSE[@]}" up -d --build web worker
fi
say "Waiting for Spendloom health check…"
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T web curl -fsS http://localhost:8080/api/health >/dev/null 2>&1; then
    say "Spendloom is ready: $APP_ORIGIN"
    say "Status: docker compose ps"
    say "Logs:   docker compose logs -f web worker"
    exit 0
  fi
  sleep 2
done
die "Spendloom did not become healthy. Inspect with: docker compose logs --tail=100 web worker"
