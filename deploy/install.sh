#!/usr/bin/env bash
# Первичная установка Python Hosting Panel на чистый Ubuntu/Debian сервер.
# Запускать от root:
#   bash install.sh https://github.com/ваш-логин/ваш-репозиторий.git
set -euo pipefail

REPO_URL="${1:?Укажите URL git-репозитория первым аргументом}"
BASE_DIR="/root/bots"

echo "==> Устанавливаю системные пакеты..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git nginx

if [ -d "$BASE_DIR/.git" ]; then
  echo "==> $BASE_DIR уже является git-репозиторием, использую update.sh"
  cd "$BASE_DIR"
  git pull
else
  echo "==> Клонирую $REPO_URL в $BASE_DIR..."
  git clone "$REPO_URL" "$BASE_DIR"
fi

cd "$BASE_DIR"
echo "==> Создаю общий venv (используется панелью и всеми проектами)..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Генерирую случайный SECRET_KEY..."
SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sed -i "s/CHANGE_ME_TO_RANDOM_VALUE/$SECRET/" deploy/panel.service

echo "==> Устанавливаю systemd unit панели..."
cp deploy/panel.service /etc/systemd/system/panel.service
systemctl daemon-reload
systemctl enable --now panel.service

echo ""
echo "Готово! Панель запущена на http://127.0.0.1:8000"
echo "Настройте nginx (см. deploy/nginx.conf.example) и TLS, затем откройте"
echo "https://ваш-домен и создайте администратора на странице /setup"
echo ""
echo "Для последующих обновлений используйте: bash deploy/update.sh"
