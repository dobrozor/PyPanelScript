import os

# Базовая директория, где хранятся все проекты пользователя
BASE_DIR = os.environ.get("PANEL_BASE_DIR", "/root/bots")

PROJECTS_DIR = os.path.join(BASE_DIR, "projects")
SYSTEMD_DIR = os.path.join(BASE_DIR, "systemd")          # локальная копия unit-файлов (для истории/бэкапа)
SYSTEMD_SYSTEM_DIR = "/etc/systemd/system"                 # куда реально ставятся unit-файлы
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(BASE_DIR, "panel.db")

# Общий venv для ВСЕХ проектов (тот же, что вы активируете через
# `source bots/venv/bin/activate`). Отдельный venv на каждый проект
# больше не создаётся — все проекты и сама панель используют один
# и тот же интерпретатор/pip.
SHARED_VENV_DIR = os.environ.get("PANEL_SHARED_VENV", os.path.join(BASE_DIR, "venv"))
SHARED_VENV_PYTHON = os.path.join(SHARED_VENV_DIR, "bin", "python")
SHARED_VENV_PIP = os.path.join(SHARED_VENV_DIR, "bin", "pip")

# Имя проекта: только буквы, цифры, - и _
PROJECT_NAME_RE = r"^[A-Za-z0-9_-]+$"

SECRET_KEY = os.environ.get("PANEL_SECRET_KEY", os.urandom(32).hex())

# Максимальный размер загружаемого файла (100 МБ)
MAX_CONTENT_LENGTH = 100 * 1024 * 1024

# Сколько строк логов показывать по умолчанию
LOG_TAIL_LINES = 500

for d in (BASE_DIR, PROJECTS_DIR, SYSTEMD_DIR, BACKUPS_DIR, LOGS_DIR):
    os.makedirs(d, exist_ok=True)
