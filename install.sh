#!/usr/bin/env bash
# PyPanel: установка одной командой.
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USER/pypanel/main/install.sh | sudo bash
# Команды: install (по умолчанию) | update | uninstall [--purge]
# Параметры через переменные: PANEL_PASSWORD, PANEL_PORT (8001), PANEL_HOST (0.0.0.0), PYPANEL_DIR (/opt/pypanel)
set -euo pipefail

REPO="${PYPANEL_REPO:-YOUR_USER/pypanel}"
BRANCH="${PYPANEL_BRANCH:-main}"
DIR="${PYPANEL_DIR:-/opt/pypanel}"
ENVF=/etc/pypanel.env
UNIT=/etc/systemd/system/pypanel.service
CMD="${1:-install}"

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mОшибка:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "запустите от root (через sudo)"
command -v systemctl >/dev/null || die "нужен systemd"

fetch() { # fetch <файл репозитория> <куда положить>
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/$1" ]; then
    cp "$(dirname "${BASH_SOURCE[0]}")/$1" "$2"
  else
    curl -fsSL "https://raw.githubusercontent.com/$REPO/$BRANCH/$1" -o "$2" || die "не удалось скачать $1 из $REPO"
  fi
}

ensure_deps() {
  if command -v python3 >/dev/null && python3 -c 'import ensurepip, venv' 2>/dev/null && command -v curl >/dev/null; then return; fi
  say "Ставлю python3, venv и curl"
  if command -v apt-get >/dev/null; then
    apt-get update -y && apt-get install -y python3 python3-venv python3-pip curl
  elif command -v dnf >/dev/null; then
    dnf install -y python3 python3-pip curl
  elif command -v yum >/dev/null; then
    yum install -y python3 python3-pip curl
  else
    die "не знаю, как поставить python3 на этой системе. Поставьте python3 + venv вручную"
  fi
}

deploy_files() {
  mkdir -p "$DIR"
  fetch app.py "$DIR/app.py"
  fetch requirements.txt "$DIR/requirements.txt"
  [ -d "$DIR/venv" ] || python3 -m venv "$DIR/venv"
  "$DIR/venv/bin/pip" install -q --upgrade pip
  "$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt"
}

case "$CMD" in
install)
  ensure_deps
  say "Устанавливаю PyPanel в $DIR"
  deploy_files

  NEWPASS=""
  if [ ! -f "$ENVF" ]; then
    PASS="${PANEL_PASSWORD:-}"
    if [ -z "$PASS" ]; then
      PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"; NEWPASS=1
    fi
    case "$PASS" in *\'*) die "в пароле нельзя использовать символ '";; esac
    PORT="${PANEL_PORT:-8001}"
    [[ "$PORT" =~ ^[0-9]+$ ]] || die "PANEL_PORT должен быть числом"
    ( umask 077; printf "PANEL_PASSWORD='%s'\nPANEL_HOST=%s\nPANEL_PORT=%s\n" "$PASS" "${PANEL_HOST:-0.0.0.0}" "$PORT" > "$ENVF" )
  else
    say "Найден $ENVF, пароль и порт оставляю прежними"
  fi

  cat > "$UNIT" <<UNITEOF
[Unit]
Description=PyPanel
After=network.target

[Service]
WorkingDirectory=$DIR
EnvironmentFile=$ENVF
ExecStart=$DIR/venv/bin/gunicorn -w 1 --threads 8 --timeout 900 -b \${PANEL_HOST}:\${PANEL_PORT} app:app
Restart=always

[Install]
WantedBy=multi-user.target
UNITEOF
  systemctl daemon-reload
  systemctl enable pypanel >/dev/null 2>&1
  systemctl restart pypanel

  set -a; . "$ENVF"; set +a
  if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "$PANEL_PORT/tcp" >/dev/null && say "Открыл порт $PANEL_PORT в ufw"
  fi
  sleep 2
  systemctl is-active --quiet pypanel || die "сервис не запустился: journalctl -u pypanel -n 50"
  IP="$(curl -fsS4 --max-time 3 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
  echo
  say "Готово. Панель: http://$IP:$PANEL_PORT"
  [ -n "$NEWPASS" ] && echo "    Пароль: $PANEL_PASSWORD   (хранится в $ENVF)"
  echo "    Обновить: curl -fsSL https://raw.githubusercontent.com/$REPO/$BRANCH/install.sh | sudo bash -s update"
  ;;
update)
  [ -d "$DIR" ] || die "PyPanel не установлена. Запустите install"
  say "Обновляю PyPanel (проекты и данные не затрагиваются)"
  deploy_files
  systemctl restart pypanel
  say "Готово"
  ;;
uninstall)
  say "Удаляю сервис"
  systemctl disable --now pypanel 2>/dev/null || true
  rm -f "$UNIT" && systemctl daemon-reload
  if [ "${2:-}" = "--purge" ]; then
    rm -rf "$DIR" "$ENVF"; say "Файлы и проекты удалены"
  else
    rm -rf "$DIR/venv" "$DIR/app.py" "$DIR/requirements.txt"
    say "Проекты сохранены в $DIR/data (полное удаление: uninstall --purge)"
  fi
  ;;
*) die "неизвестная команда: $CMD (install | update | uninstall)" ;;
esac
