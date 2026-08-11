#!/usr/bin/env bash
# Stop Spendloom without silently destroying its private financial data.
set -Eeuo pipefail
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=scripts/lib.sh
. "$ROOT_DIR/scripts/lib.sh"

REMOVE_IMAGES=0; PURGE=0
for arg in "$@"; do
  case $arg in --remove-images) REMOVE_IMAGES=1;; --purge) PURGE=1;; -h|--help) say "Usage: ./uninstall.sh [--remove-images] [--purge]"; exit 0;; *) die "Unknown option: $arg";; esac
done
have docker || die "Docker is not installed; no Spendloom containers were changed."
[[ -f $ROOT_DIR/docker-compose.yml ]] || die "This does not look like a Spendloom installation."

if ((PURGE)); then
  [[ -d $ROOT_DIR/data ]] || die "No data directory exists to purge."
  archive_parent=$(dirname "$ROOT_DIR")
  archive="$archive_parent/spendloom-final-archive-$(date +%Y%m%dT%H%M%S).tar.gz"
  say "Purge creates a final archive outside the installation: $archive"
  if [[ ${SPENDLOOM_NONINTERACTIVE:-0} == 1 ]]; then
    [[ ${SPENDLOOM_PURGE_CONFIRM:-} == "PURGE SPENDLOOM" ]] || die "Set SPENDLOOM_PURGE_CONFIRM='PURGE SPENDLOOM' for non-interactive purge."
  else
    read -r -p "Type PURGE SPENDLOOM to archive then remove receipts, database, backups, and .env: " phrase
    [[ $phrase == "PURGE SPENDLOOM" ]] || die "Purge cancelled."
  fi
  tar -C "$ROOT_DIR" -czf "$archive" data .env 2>/dev/null || tar -C "$ROOT_DIR" -czf "$archive" data
fi

compose=(docker compose)
if ((REMOVE_IMAGES)); then "${compose[@]}" down --remove-orphans --rmi local; else "${compose[@]}" down --remove-orphans; fi
if ((PURGE)); then
  # This target is explicit and validated above; the final archive is outside it.
  rm -rf "$ROOT_DIR/data" "$ROOT_DIR/.env"
  say "Spendloom data and configuration were purged. Final archive: $archive"
else
  say "Spendloom containers and networks were removed. .env, receipts, database, and backups were preserved."
fi
