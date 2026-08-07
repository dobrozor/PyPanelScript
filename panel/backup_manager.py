import datetime as dt
import os
import tarfile

from . import config


def create_backup(project_name):
    proj_dir = os.path.join(config.PROJECTS_DIR, project_name)
    if not os.path.isdir(proj_dir):
        raise FileNotFoundError(project_name)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{project_name}_{timestamp}.tar.gz"
    backup_path = os.path.join(config.BACKUPS_DIR, backup_name)

    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add(proj_dir, arcname=project_name, exclude=lambda p: "/venv" in p)

    return backup_name


def list_backups(project_name=None):
    backups = []
    for fname in sorted(os.listdir(config.BACKUPS_DIR), reverse=True):
        if not fname.endswith(".tar.gz"):
            continue
        if project_name and not fname.startswith(project_name + "_"):
            continue
        full = os.path.join(config.BACKUPS_DIR, fname)
        backups.append(
            {
                "name": fname,
                "size": os.path.getsize(full),
                "modified": os.path.getmtime(full),
            }
        )
    return backups


def restore_backup(backup_name):
    backup_path = os.path.join(config.BACKUPS_DIR, backup_name)
    if not os.path.exists(backup_path):
        raise FileNotFoundError(backup_name)
    with tarfile.open(backup_path, "r:gz") as tar:
        tar.extractall(config.PROJECTS_DIR)


def delete_backup(backup_name):
    path = os.path.join(config.BACKUPS_DIR, backup_name)
    if os.path.exists(path):
        os.remove(path)
