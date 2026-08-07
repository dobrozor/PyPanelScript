#!/usr/bin/env bash
# Быстрое обновление панели из GitHub — забирает новый код и перезапускает сервис.
# Запускать от root на сервере: bash /root/bots/deploy/update.sh
set -euo pipefail

BASE_DIR="/root/bots"
cd "$BASE_DIR"

echo "==> Забираю последние изменения из git..."
git pull

echo "==> Обновляю зависимости панели (requirements.txt)..."
./venv/bin/pip install -r requirements.txt

echo "==> Перезапускаю panel.service..."
systemctl restart panel.service

echo "Готово. Статус:"
systemctl status panel.service --no-pager -l | head -n 8
