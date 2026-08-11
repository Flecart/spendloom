#!/usr/bin/env bash
# Shared, deliberately conservative helpers for Spendloom's local scripts.
set -Eeuo pipefail

say() { printf '%s\n' "$*"; }
die() { say "Error: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

confirm() {
  local prompt=${1:?prompt required}
  if [[ ${SPENDLOOM_NONINTERACTIVE:-0} == 1 ]]; then return 0; fi
  local answer
  read -r -p "$prompt [y/N] " answer
  [[ $answer =~ ^[Yy]([Ee][Ss])?$ ]]
}

need_sudo() {
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then SUDO=(); return; fi
  have sudo || die "sudo is required to install packages or manage Docker on this host."
  sudo -v || die "sudo authorization was not granted."
  SUDO=(sudo)
}

detect_platform() {
  [[ -r /etc/os-release ]] || die "Unsupported distribution. Install Docker Engine and Compose v2 manually, then rerun."
  # shellcheck disable=SC1091
  . /etc/os-release
  DISTRO_ID=${ID,,}
  DISTRO_LIKE=${ID_LIKE:-}
  case " $DISTRO_ID $DISTRO_LIKE " in
    *" debian "*|*" ubuntu "*) PACKAGE_FAMILY=apt ;;
    *" fedora "*|*" rhel "*) PACKAGE_FAMILY=dnf ;;
    *" arch "*) PACKAGE_FAMILY=pacman ;;
    *) die "Unsupported distribution ($DISTRO_ID). Install Docker Engine and Compose v2 manually, then rerun." ;;
  esac
  ARCH=$(uname -m)
  case $ARCH in x86_64|aarch64|armv7l) ;; *) die "Unsupported architecture: $ARCH" ;; esac
}

install_docker_packages() {
  need_sudo
  case $PACKAGE_FAMILY in
    apt)
      "${SUDO[@]}" apt-get update
      "${SUDO[@]}" apt-get install -y docker.io docker-compose-plugin || "${SUDO[@]}" apt-get install -y docker.io docker-compose
      ;;
    dnf) "${SUDO[@]}" dnf install -y docker docker-compose-plugin ;;
    pacman) "${SUDO[@]}" pacman -Sy --needed --noconfirm docker docker-compose ;;
  esac
  "${SUDO[@]}" systemctl enable --now docker
}

ensure_docker() {
  if ! have docker || ! docker compose version >/dev/null 2>&1; then
    confirm "Docker Engine and Compose v2 are missing. Install signed distribution packages now?" || die "Install Docker Engine and Compose v2, then rerun."
    install_docker_packages
  fi
  if ! docker info >/dev/null 2>&1; then
    need_sudo
    "${SUDO[@]}" systemctl enable --now docker || die "Docker is installed but the daemon could not be started."
  fi
  docker info >/dev/null 2>&1 || die "Docker daemon is not available to this user. Log out and back in after adding yourself to the docker group, or rerun with appropriate access."
}

port_in_use() {
  local port=${1:?port required}
  if have ss; then ss -ltn "sport = :$port" | awk 'NR>1 {found=1} END {exit !found}'; return; fi
  if have lsof; then lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; return; fi
  return 1
}

random_secret() {
  if have openssl; then openssl rand -base64 48 | tr -d '\n'; else head -c 48 /dev/urandom | base64 | tr -d '\n'; fi
}

env_get() {
  local file=${1:?file}; local wanted=${2:?key}
  [[ -f $file ]] || return 0
  awk -F= -v key="$wanted" '$1==key {sub(/^[^=]*=/, ""); print; exit}' "$file"
}

env_set() {
  local file=${1:?file} key=${2:?key} value=${3-}
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i.bak "/^${key}=/c\\${key}=${value}" "$file"
    rm -f "${file}.bak"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}
