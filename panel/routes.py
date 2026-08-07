import json
import os
import re

import pyotp
from flask import (
    Blueprint, jsonify, redirect, render_template, request,
    send_file, url_for, flash, abort,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

from . import config, backup_manager, git_manager, monitor, pip_manager, scheduler
from .auth import User
from .db import db_session
from .file_manager import (
    PathError, create_dir, create_file, delete_path, list_dir,
    move_path, read_file, rename_path, safe_path, write_file,
)
from .systemd_manager import (
    create_unit, disable, enable, get_pid, is_enabled, journal_tail,
    remove_unit, restart, start, status, stop,
)

bp = Blueprint("main", __name__)


# ---------------------------------------------------------------- helpers

def project_name_valid(name):
    return bool(re.match(config.PROJECT_NAME_RE, name or ""))


def get_project_row(name):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        abort(404)
    return row


# ---------------------------------------------------------------- auth

@bp.route("/setup", methods=["GET", "POST"])
def setup():
    """Первый запуск: создание единственного администратора панели."""
    if User.count() > 0:
        return redirect(url_for("main.login"))

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if len(password) < 8:
            flash("Пароль должен быть не короче 8 символов", "error")
            return render_template("setup.html")
        User.create(username, password)
        flash("Администратор создан, теперь войдите", "success")
        return redirect(url_for("main.login"))

    return render_template("setup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if User.count() == 0:
        return redirect(url_for("main.setup"))
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        totp_code = request.form.get("totp_code", "")

        user = User.get_by_username(username)
        if not user:
            flash("Неверный логин или пароль", "error")
            return render_template("login.html")

        if user.is_locked():
            flash("Аккаунт временно заблокирован из-за неудачных попыток входа", "error")
            return render_template("login.html")

        if not user.check_password(password):
            user.register_failed_attempt()
            flash("Неверный логин или пароль", "error")
            return render_template("login.html")

        if user.totp_enabled and not user.verify_totp(totp_code):
            flash("Неверный код двухфакторной аутентификации", "error")
            return render_template("login.html")

        user.reset_failed_attempts()
        login_user(user)
        return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))


@bp.route("/settings/security", methods=["GET", "POST"])
@login_required
def security_settings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "change_password":
            if not current_user.check_password(request.form["current_password"]):
                flash("Текущий пароль неверен", "error")
            elif len(request.form["new_password"]) < 8:
                flash("Новый пароль слишком короткий", "error")
            else:
                current_user.set_password(request.form["new_password"])
                flash("Пароль обновлён", "success")
        elif action == "enable_totp":
            secret = pyotp.random_base32()
            current_user.enable_totp(secret)
            flash("2FA включена", "success")
        elif action == "disable_totp":
            current_user.disable_totp()
            flash("2FA отключена", "success")
    return render_template("security.html", user=current_user)


# ---------------------------------------------------------------- dashboard

@bp.route("/")
@login_required
def dashboard():
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    projects = []
    for row in rows:
        projects.append(
            {
                "name": row["name"],
                "status": status(row["name"]),
                "enabled": is_enabled(row["name"]),
                "pid": get_pid(row["name"]),
            }
        )
    return render_template("dashboard.html", projects=projects, sys_stats=monitor.system_stats())


@bp.route("/api/system-stats")
@login_required
def api_system_stats():
    return jsonify(monitor.system_stats())


# ---------------------------------------------------------------- project CRUD

@bp.route("/projects", methods=["POST"])
@login_required
def create_project():
    name = request.form.get("name", "").strip()
    if not project_name_valid(name):
        flash("Имя проекта может содержать только латинские буквы, цифры, - и _", "error")
        return redirect(url_for("main.dashboard"))

    proj_dir = os.path.join(config.PROJECTS_DIR, name)
    if os.path.exists(proj_dir):
        flash("Проект с таким именем уже существует", "error")
        return redirect(url_for("main.dashboard"))

    os.makedirs(proj_dir)
    with open(os.path.join(proj_dir, "main.py"), "w") as f:
        f.write('print("Hello World")\n')
    with open(os.path.join(proj_dir, "requirements.txt"), "w") as f:
        f.write("")
    with open(os.path.join(proj_dir, "README.md"), "w") as f:
        f.write(f"# {name}\n")
    with open(os.path.join(proj_dir, "config.json"), "w") as f:
        json.dump({}, f)

    with db_session() as conn:
        conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))

    create_unit(name, entry_file="main.py")
    flash(f"Проект «{name}» создан", "success")
    return redirect(url_for("main.project_page", name=name))


@bp.route("/projects/<name>/delete", methods=["POST"])
@login_required
def delete_project(name):
    get_project_row(name)
    remove_unit(name)
    scheduler.remove_timer(name)
    proj_dir = os.path.join(config.PROJECTS_DIR, name)
    import shutil
    if os.path.isdir(proj_dir):
        shutil.rmtree(proj_dir)
    with db_session() as conn:
        conn.execute("DELETE FROM projects WHERE name = ?", (name,))
    flash(f"Проект «{name}» удалён", "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/projects/<name>")
@login_required
def project_page(name):
    row = get_project_row(name)
    return render_template(
        "project.html",
        project=row,
        status=status(name),
        enabled=is_enabled(name),
        pid=get_pid(name),
        files=list_dir(name, ""),
        backups=backup_manager.list_backups(name),
        is_git=git_manager.is_repo(name),
    )


@bp.route("/projects/<name>/settings", methods=["POST"])
@login_required
def project_settings(name):
    row = get_project_row(name)
    entry_file = request.form.get("entry_file", row["entry_file"])
    args = request.form.get("args", "")
    env_raw = request.form.get("env", "{}")
    try:
        env = json.loads(env_raw) if env_raw.strip() else {}
    except json.JSONDecodeError:
        flash("Переменные окружения должны быть в формате JSON", "error")
        return redirect(url_for("main.project_page", name=name))

    with db_session() as conn:
        conn.execute(
            "UPDATE projects SET entry_file = ?, args = ?, env_json = ? WHERE name = ?",
            (entry_file, args, json.dumps(env), name),
        )

    create_unit(name, entry_file=entry_file, args=args, env=env)
    flash("Настройки сохранены, сервис обновлён", "success")
    return redirect(url_for("main.project_page", name=name))


# ---------------------------------------------------------------- process control

@bp.route("/projects/<name>/control/<action>", methods=["POST"])
@login_required
def control_project(name, action):
    get_project_row(name)
    actions = {
        "start": start, "stop": stop, "restart": restart,
        "enable": enable, "disable": disable,
    }
    if action not in actions:
        abort(400)
    ok, err = actions[action](name)
    if not ok:
        flash(f"Ошибка: {err}", "error")
    return redirect(url_for("main.project_page", name=name))


@bp.route("/api/projects/<name>/status")
@login_required
def api_project_status(name):
    get_project_row(name)
    stats = monitor.project_stats(name)
    return jsonify(
        {
            "status": status(name),
            "enabled": is_enabled(name),
            "pid": get_pid(name),
            "stats": stats,
        }
    )


# ---------------------------------------------------------------- logs

@bp.route("/projects/<name>/logs")
@login_required
def project_logs(name):
    get_project_row(name)
    lines = int(request.args.get("lines", config.LOG_TAIL_LINES))
    log_path = os.path.join(config.LOGS_DIR, f"{name}.log")
    content = ""
    if os.path.exists(log_path):
        with open(log_path, "r", errors="replace") as f:
            all_lines = f.readlines()
            content = "".join(all_lines[-lines:])
    return jsonify({"log": content, "journal": journal_tail(name, lines)})


# ---------------------------------------------------------------- files

@bp.route("/projects/<name>/files")
@login_required
def api_list_files(name):
    get_project_row(name)
    rel = request.args.get("path", "")
    try:
        return jsonify(list_dir(name, rel))
    except PathError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/projects/<name>/files/content")
@login_required
def api_read_file(name):
    get_project_row(name)
    rel = request.args.get("path", "")
    try:
        return jsonify({"content": read_file(name, rel)})
    except PathError as e:
        return jsonify({"error": str(e)}), 400
    except UnicodeDecodeError:
        return jsonify({"error": "Бинарный файл, редактирование недоступно"}), 400


@bp.route("/projects/<name>/files/save", methods=["POST"])
@login_required
def api_save_file(name):
    get_project_row(name)
    data = request.get_json()
    try:
        write_file(name, data["path"], data["content"])
        return jsonify({"ok": True})
    except PathError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/projects/<name>/files/create", methods=["POST"])
@login_required
def api_create_file(name):
    get_project_row(name)
    data = request.get_json()
    try:
        if data.get("type") == "dir":
            create_dir(name, data["path"])
        else:
            create_file(name, data["path"])
        return jsonify({"ok": True})
    except PathError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/projects/<name>/files/delete", methods=["POST"])
@login_required
def api_delete_file(name):
    get_project_row(name)
    data = request.get_json()
    try:
        delete_path(name, data["path"])
        return jsonify({"ok": True})
    except PathError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/projects/<name>/files/rename", methods=["POST"])
@login_required
def api_rename_file(name):
    get_project_row(name)
    data = request.get_json()
    try:
        rename_path(name, data["path"], data["new_name"])
        return jsonify({"ok": True})
    except PathError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/projects/<name>/files/move", methods=["POST"])
@login_required
def api_move_file(name):
    get_project_row(name)
    data = request.get_json()
    try:
        move_path(name, data["src"], data["dest"])
        return jsonify({"ok": True})
    except PathError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/projects/<name>/files/download")
@login_required
def api_download_file(name):
    get_project_row(name)
    rel = request.args.get("path", "")
    try:
        path = safe_path(name, rel)
    except PathError as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True)


@bp.route("/projects/<name>/files/upload", methods=["POST"])
@login_required
def api_upload_file(name):
    get_project_row(name)
    rel_dir = request.form.get("path", "")
    uploaded = request.files.getlist("files")
    try:
        target_dir = safe_path(name, rel_dir)
    except PathError as e:
        return jsonify({"error": str(e)}), 400
    os.makedirs(target_dir, exist_ok=True)
    for f in uploaded:
        filename = secure_filename(f.filename)
        f.save(os.path.join(target_dir, filename))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- requirements / pip

@bp.route("/projects/<name>/requirements/install", methods=["POST"])
@login_required
def api_install_requirements(name):
    get_project_row(name)
    ok, output = pip_manager.install_requirements(name)
    return jsonify({"ok": ok, "output": output})


@bp.route("/projects/<name>/requirements/install-package", methods=["POST"])
@login_required
def api_install_package(name):
    get_project_row(name)
    package = request.get_json().get("package", "").strip()
    if not package:
        return jsonify({"error": "Не указано имя пакета"}), 400
    ok, output = pip_manager.install_package(name, package)
    return jsonify({"ok": ok, "output": output})


@bp.route("/projects/<name>/requirements/freeze")
@login_required
def api_freeze(name):
    get_project_row(name)
    return jsonify({"freeze": pip_manager.freeze(name)})


# ---------------------------------------------------------------- git

@bp.route("/projects/<name>/git/<action>", methods=["POST"])
@login_required
def api_git(name, action):
    get_project_row(name)
    data = request.get_json(silent=True) or {}
    if action == "init":
        ok, out = git_manager.init(name)
    elif action == "remote":
        ok, out = git_manager.add_remote(name, data.get("url", ""))
    elif action == "commit":
        ok, out = git_manager.commit(name, data.get("message", "update"))
    elif action == "push":
        ok, out = git_manager.push(name, data.get("branch", "main"))
    elif action == "pull":
        ok, out = git_manager.pull(name, data.get("branch", "main"))
    else:
        abort(400)
    return jsonify({"ok": ok, "output": out})


# ---------------------------------------------------------------- backups

@bp.route("/projects/<name>/backup", methods=["POST"])
@login_required
def api_create_backup(name):
    get_project_row(name)
    backup_name = backup_manager.create_backup(name)
    return jsonify({"ok": True, "backup": backup_name})


@bp.route("/projects/<name>/backup/<backup_name>/restore", methods=["POST"])
@login_required
def api_restore_backup(name, backup_name):
    get_project_row(name)
    backup_manager.restore_backup(backup_name)
    return jsonify({"ok": True})


@bp.route("/projects/<name>/backup/<backup_name>/delete", methods=["POST"])
@login_required
def api_delete_backup(name, backup_name):
    get_project_row(name)
    backup_manager.delete_backup(backup_name)
    return jsonify({"ok": True})


@bp.route("/projects/<name>/backup/<backup_name>/download")
@login_required
def api_download_backup(name, backup_name):
    get_project_row(name)
    path = os.path.join(config.BACKUPS_DIR, secure_filename(backup_name))
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True)


# ---------------------------------------------------------------- import project

@bp.route("/projects/import", methods=["POST"])
@login_required
def import_project():
    name = request.form.get("name", "").strip()
    archive = request.files.get("archive")
    if not project_name_valid(name) or not archive:
        flash("Некорректное имя проекта или файл не выбран", "error")
        return redirect(url_for("main.dashboard"))

    proj_dir = os.path.join(config.PROJECTS_DIR, name)
    if os.path.exists(proj_dir):
        flash("Проект с таким именем уже существует", "error")
        return redirect(url_for("main.dashboard"))

    os.makedirs(proj_dir)
    tmp_path = os.path.join(proj_dir, "_import" + os.path.splitext(archive.filename)[1])
    archive.save(tmp_path)

    import shutil
    shutil.unpack_archive(tmp_path, proj_dir)
    os.remove(tmp_path)

    with db_session() as conn:
        conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    create_unit(name)
    flash(f"Проект «{name}» импортирован", "success")
    return redirect(url_for("main.project_page", name=name))


# ---------------------------------------------------------------- scheduler

@bp.route("/projects/<name>/schedule", methods=["POST"])
@login_required
def api_set_schedule(name):
    get_project_row(name)
    on_calendar = request.get_json().get("on_calendar", "").strip()
    if not on_calendar:
        scheduler.remove_timer(name)
        return jsonify({"ok": True, "removed": True})
    scheduler.create_timer(name, on_calendar)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- search

@bp.route("/api/search")
@login_required
def api_search():
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify({"results": []})

    results = []
    for root, dirs, files in os.walk(config.PROJECTS_DIR):
        dirs[:] = [d for d in dirs if d not in ("venv", ".git", "__pycache__")]
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, config.PROJECTS_DIR)
            if query.lower() in fname.lower():
                results.append({"type": "file", "path": rel})
                continue
            if os.path.getsize(full) > 2_000_000:
                continue
            try:
                with open(full, "r", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            results.append(
                                {"type": "content", "path": rel, "line": i, "text": line.strip()[:200]}
                            )
                            break
            except (UnicodeDecodeError, OSError):
                continue
            if len(results) >= 100:
                break
    return jsonify({"results": results[:100]})
