import os
import subprocess

from . import config


def ensure_shared_venv():
    """
    Проверяет, что общий venv существует. В отличие от прошлой версии,
    venv на каждый проект больше не создаётся — используется общий
    venv, который вы сами создали и активируете через
    `source bots/venv/bin/activate`.
    """
    if not os.path.exists(config.SHARED_VENV_PYTHON):
        raise FileNotFoundError(
            f"Общий venv не найден по пути {config.SHARED_VENV_DIR}. "
            f"Создайте его: python3 -m venv {config.SHARED_VENV_DIR}"
        )
    return config.SHARED_VENV_DIR


def install_requirements(project_name):
    """
    Ставит зависимости проекта из requirements.txt в общий venv.
    Возвращает (успех, вывод).
    """
    proj_dir = os.path.join(config.PROJECTS_DIR, project_name)
    req_file = os.path.join(proj_dir, "requirements.txt")
    if not os.path.exists(req_file):
        return False, "requirements.txt не найден"

    try:
        ensure_shared_venv()
    except FileNotFoundError as e:
        return False, str(e)

    result = subprocess.run(
        [config.SHARED_VENV_PIP, "install", "-r", "requirements.txt"],
        cwd=proj_dir,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return result.returncode == 0, (result.stdout + "\n" + result.stderr)


def install_package(project_name, package_name):
    try:
        ensure_shared_venv()
    except FileNotFoundError as e:
        return False, str(e)

    result = subprocess.run(
        [config.SHARED_VENV_PIP, "install", package_name],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode == 0, (result.stdout + "\n" + result.stderr)


def freeze(project_name=None):
    """
    project_name оставлен для обратной совместимости с вызовами из routes.py,
    но больше не используется — freeze всегда идёт по общему venv.
    """
    if not os.path.exists(config.SHARED_VENV_PIP):
        return ""
    result = subprocess.run(
        [config.SHARED_VENV_PIP, "freeze"], capture_output=True, text=True, timeout=60
    )
    return result.stdout
