"""
Планировщик на основе systemd timers.
Позволяет запускать проект по расписанию (OnCalendar) в дополнение
к постоянно работающему сервису.
"""
import os
import subprocess

from . import config
from .systemd_manager import unit_name, SERVICE_PREFIX

PRESETS = {
    "every_5_min": "*:0/5",
    "hourly": "hourly",
    "daily": "daily",
}


def timer_name(project_name):
    return f"{SERVICE_PREFIX}{project_name}.timer"


def create_timer(project_name, on_calendar: str):
    """on_calendar — выражение вида 'hourly', 'daily', '*:0/5' и т.п."""
    timer_content = f"""[Unit]
Description=Timer for {project_name}

[Timer]
OnCalendar={on_calendar}
Persistent=true

[Install]
WantedBy=timers.target
"""
    path = os.path.join(config.SYSTEMD_SYSTEM_DIR, timer_name(project_name))
    with open(path, "w") as f:
        f.write(timer_content)

    subprocess.run(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "enable", "--now", timer_name(project_name)])


def remove_timer(project_name):
    name = timer_name(project_name)
    subprocess.run(["systemctl", "disable", "--now", name])
    path = os.path.join(config.SYSTEMD_SYSTEM_DIR, name)
    if os.path.exists(path):
        os.remove(path)
    subprocess.run(["systemctl", "daemon-reload"])


def timer_status(project_name):
    name = timer_name(project_name)
    result = subprocess.run(
        ["systemctl", "is-active", name], capture_output=True, text=True
    )
    return result.stdout.strip()
