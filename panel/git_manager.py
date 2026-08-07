import os
import subprocess

from . import config


def _run(project_name, args):
    proj_dir = os.path.join(config.PROJECTS_DIR, project_name)
    result = subprocess.run(
        ["git", *args], cwd=proj_dir, capture_output=True, text=True, timeout=120
    )
    return result.returncode == 0, (result.stdout + result.stderr)


def is_repo(project_name):
    proj_dir = os.path.join(config.PROJECTS_DIR, project_name)
    return os.path.isdir(os.path.join(proj_dir, ".git"))


def init(project_name):
    return _run(project_name, ["init"])


def add_remote(project_name, url):
    return _run(project_name, ["remote", "add", "origin", url])


def commit(project_name, message):
    ok1, out1 = _run(project_name, ["add", "-A"])
    ok2, out2 = _run(project_name, ["commit", "-m", message])
    return ok1 and ok2, out1 + "\n" + out2


def push(project_name, branch="main"):
    return _run(project_name, ["push", "-u", "origin", branch])


def pull(project_name, branch="main"):
    return _run(project_name, ["pull", "origin", branch])


def log(project_name, limit=20):
    ok, out = _run(project_name, ["log", f"-{limit}", "--oneline"])
    return out
