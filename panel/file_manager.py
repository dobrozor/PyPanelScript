import os
import shutil

from . import config


class PathError(Exception):
    pass


def project_root(project_name: str) -> str:
    root = os.path.join(config.PROJECTS_DIR, project_name)
    if not os.path.isdir(root):
        raise PathError("Проект не найден")
    return root


def safe_path(project_name: str, relative_path: str) -> str:
    """
    Возвращает абсолютный путь внутри папки проекта,
    гарантированно не выходящий за её пределы (защита от ../../).
    """
    root = os.path.realpath(project_root(project_name))
    candidate = os.path.realpath(os.path.join(root, relative_path.lstrip("/")))
    if candidate != root and not candidate.startswith(root + os.sep):
        raise PathError("Недопустимый путь")
    return candidate


def list_dir(project_name: str, relative_path: str = ""):
    path = safe_path(project_name, relative_path)
    if not os.path.isdir(path):
        raise PathError("Не директория")
    entries = []
    for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
        entries.append(
            {
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
                "modified": entry.stat().st_mtime,
            }
        )
    return entries


def read_file(project_name: str, relative_path: str) -> str:
    path = safe_path(project_name, relative_path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_file(project_name: str, relative_path: str, content: str):
    path = safe_path(project_name, relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def create_file(project_name: str, relative_path: str):
    path = safe_path(project_name, relative_path)
    if os.path.exists(path):
        raise PathError("Файл уже существует")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "a").close()


def create_dir(project_name: str, relative_path: str):
    path = safe_path(project_name, relative_path)
    os.makedirs(path, exist_ok=True)


def delete_path(project_name: str, relative_path: str):
    path = safe_path(project_name, relative_path)
    if path == os.path.realpath(project_root(project_name)):
        raise PathError("Нельзя удалить корень проекта")
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def rename_path(project_name: str, relative_path: str, new_name: str):
    if "/" in new_name or new_name in ("..", "."):
        raise PathError("Недопустимое имя")
    old_path = safe_path(project_name, relative_path)
    new_path = os.path.join(os.path.dirname(old_path), new_name)
    os.rename(old_path, new_path)


def move_path(project_name: str, src_relative: str, dest_relative: str):
    src = safe_path(project_name, src_relative)
    dest = safe_path(project_name, dest_relative)
    shutil.move(src, dest)
