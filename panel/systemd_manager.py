"""
Модуль для создания unit-файлов systemd и управления ими
(start/stop/restart/enable/disable/status) через subprocess.

Никаких SSH-паролей и удалённых подключений — всё выполняется
локально на сервере, где запущена панель, поэтому панель должна
работать под пользователем с правами на systemctl (root или sudo
с NOPASSWD на systemctl для конкретных unit-ов).
"""
import os
import re
import shlex
import subprocess

from . import config

SERVICE_PREFIX = "panelbot-"  # чтобы не пересекаться с другими unit-ами в системе


def unit_name(project_name: str) -> str:
    return f"{SERVICE_PREFIX}{project_name}.service"


def _run(cmd, check=False):
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, check=check
    )


def create_unit(project_name: str, entry_file: str = "main.py",
                 args: str = "", env: dict | None = None,
                 working_dir: str | None = None):
    """Создаёт unit-файл для проекта и делает daemon-reload."""
    env = env or {}
    working_dir = working_dir or os.path.join(config.PROJECTS_DIR, project_name)
    # Все проекты используют один и тот же общий venv (bots/venv),
    # а не отдельный venv на каждый проект.
    python_bin = (
        config.SHARED_VENV_PYTHON
        if os.path.exists(config.SHARED_VENV_PYTHON)
        else "python3"
    )

    exec_cmd = f"{python_bin} {shlex.quote(entry_file)}"
    if args:
        exec_cmd += f" {args}"

    env_lines = "\n".join(f'Environment="{k}={v}"' for k, v in env.items())

    unit_content = f"""[Unit]
Description=PanelBot project: {project_name}
After=network.target

[Service]
Type=simple
WorkingDirectory={working_dir}
ExecStart={exec_cmd}
Restart=on-failure
RestartSec=5
StandardOutput=append:{config.LOGS_DIR}/{project_name}.log
StandardError=append:{config.LOGS_DIR}/{project_name}.log
{env_lines}

[Install]
WantedBy=multi-user.target
"""

    # локальная копия (для истории/бэкапов, не обязательна systemd)
    local_path = os.path.join(config.SYSTEMD_DIR, unit_name(project_name))
    with open(local_path, "w") as f:
        f.write(unit_content)

    # реальный unit-файл
    system_path = os.path.join(config.SYSTEMD_SYSTEM_DIR, unit_name(project_name))
    with open(system_path, "w") as f:
        f.write(unit_content)

    _run(["systemctl", "daemon-reload"])
    return system_path


def remove_unit(project_name: str):
    name = unit_name(project_name)
    _run(["systemctl", "stop", name])
    _run(["systemctl", "disable", name])
    system_path = os.path.join(config.SYSTEMD_SYSTEM_DIR, name)
    if os.path.exists(system_path):
        os.remove(system_path)
    local_path = os.path.join(config.SYSTEMD_DIR, name)
    if os.path.exists(local_path):
        os.remove(local_path)
    _run(["systemctl", "daemon-reload"])


def _ctl(action: str, project_name: str):
    name = unit_name(project_name)
    if action not in ("start", "stop", "restart", "reload", "enable", "disable"):
        raise ValueError("invalid action")
    result = _run(["systemctl", action, name])
    return result.returncode == 0, result.stderr.strip()


def start(project_name):
    return _ctl("start", project_name)


def stop(project_name):
    return _ctl("stop", project_name)


def restart(project_name):
    return _ctl("restart", project_name)


def enable(project_name):
    return _ctl("enable", project_name)


def disable(project_name):
    return _ctl("disable", project_name)


def status(project_name) -> str:
    """Возвращает 'active', 'inactive', 'failed' и т.д."""
    name = unit_name(project_name)
    result = _run(["systemctl", "is-active", name])
    return result.stdout.strip() or "unknown"


def is_enabled(project_name) -> bool:
    name = unit_name(project_name)
    result = _run(["systemctl", "is-enabled", name])
    return result.stdout.strip() == "enabled"


def get_pid(project_name) -> int | None:
    name = unit_name(project_name)
    result = _run(["systemctl", "show", name, "--property=MainPID"])
    m = re.search(r"MainPID=(\d+)", result.stdout)
    if m:
        pid = int(m.group(1))
        return pid if pid != 0 else None
    return None


def journal_tail(project_name, lines=200):
    name = unit_name(project_name)
    result = _run(["journalctl", "-u", name, "-n", str(lines), "--no-pager"])
    return result.stdout
