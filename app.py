"""PyPanel: панель для хостинга python-проектов на VPS с одним общим venv.

Запуск (из venv):  PANEL_PASSWORD=... gunicorn -w 1 --threads 8 --timeout 900 -b 0.0.0.0:8001 app:app
Нужен ровно 1 воркер: состояние процессов хранится в памяти.
"""
import hmac, json, os, re, secrets, shlex, shutil, signal, subprocess, sys, tempfile, threading, time, zipfile
from datetime import timedelta
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, request, send_file, session
from werkzeug.exceptions import HTTPException

BASE = Path(__file__).resolve().parent
DATA, PROJ, LOGS = BASE / "data", BASE / "data/projects", BASE / "data/logs"
for d in (PROJ, LOGS):
    d.mkdir(parents=True, exist_ok=True)
META = DATA / "meta.json"
PASSWORD = os.environ.get("PANEL_PASSWORD", "")
if not PASSWORD:
    sys.exit("Задайте переменную PANEL_PASSWORD")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

app = Flask(__name__)
_sk = DATA / "secret"
if not _sk.exists():
    _sk.write_text(secrets.token_hex(32))
app.secret_key = _sk.read_text()
app.config.update(MAX_CONTENT_LENGTH=200 * 1024 * 1024, MAX_FORM_PARTS=100000, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_HTTPONLY=True, PERMANENT_SESSION_LIFETIME=timedelta(days=30))

lock = threading.RLock()
meta = json.loads(META.read_text()) if META.exists() else {}
state = {}


def save():
    META.write_text(json.dumps(meta, indent=2, ensure_ascii=False))


def st(n):
    return state.setdefault(n, dict(p=None, since=0, fails=0, next=0, code=None, restarts=0))


def parse_env(text):
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ---------- процессы ----------
def spawn(n):
    m, s = meta[n], st(n)
    cmd = m["command"].replace("{python}", shlex.quote(sys.executable)).replace("{port}", str(m["port"]))
    env = os.environ.copy()
    env.pop("PANEL_PASSWORD", None)
    bindir = Path(sys.executable).parent
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env.update(PORT=str(m["port"]), PYTHONUNBUFFERED="1", VIRTUAL_ENV=str(bindir.parent))
    env.update(parse_env(m.get("env")))
    lp = LOGS / f"{n}.log"
    if lp.exists() and lp.stat().st_size > 5_000_000:
        lp.write_bytes(lp.read_bytes()[-1_000_000:])
    log = open(lp, "ab")
    log.write(f"\n--- запуск {time.strftime('%F %T')} ---\n".encode())
    s["since"] = time.time()
    try:
        s["p"] = subprocess.Popen(shlex.split(cmd), cwd=PROJ / n, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        log.write(f"[panel] не удалось запустить: {e}\n".encode())
        s["fails"] += 1
        s["next"] = time.time() + min(60, 2 ** s["fails"])
    finally:
        log.close()


def kill(n):
    s = st(n)
    p = s["p"]
    if p and p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
    s["p"] = None


def supervisor():
    """Раз в 2 секунды поднимает упавшие проекты (с нарастающей паузой при быстрых падениях)."""
    while True:
        with lock:
            for n, m in list(meta.items()):
                s = st(n)
                p = s["p"]
                if p and p.poll() is not None:
                    s["code"], s["p"] = p.returncode, None
                    s["fails"] = s["fails"] + 1 if time.time() - s["since"] < 15 else 0
                    s["next"] = time.time() + min(60, 2 ** s["fails"])
                    s["restarts"] += 1
                if m["desired"] and not s["p"] and time.time() >= s["next"]:
                    spawn(n)
        time.sleep(2)


threading.Thread(target=supervisor, daemon=True).start()


# ---------- файлы ----------
def safe(root, rel=""):
    r = Path(root).resolve()
    t = (r / (rel or "")).resolve()
    if t != r and r not in t.parents:
        raise ValueError("Недопустимый путь")
    return t


def deploy(dest, files, strip=False, sub=""):
    """Кладёт файлы в папку проекта, сохраняя вложенные папки.
    Один .zip распаковывается; strip убирает общую корневую папку (для загрузки папки целиком)."""
    dest.mkdir(parents=True, exist_ok=True)
    base = safe(dest, sub)
    fs = [f for f in files if f.filename]
    items, zipmode = [], False
    if len(fs) == 1 and fs[0].filename.lower().endswith(".zip"):
        zipmode = True
        tmp = tempfile.TemporaryFile()
        shutil.copyfileobj(fs[0].stream, tmp)
        tmp.seek(0)
        z = zipfile.ZipFile(tmp)
        for i in z.infolist():
            if i.is_dir() or i.filename.startswith("__MACOSX") or i.filename.endswith(".DS_Store"):
                continue
            items.append((i.filename, lambda i=i: z.open(i)))
    else:
        items = [(f.filename, lambda f=f: f.stream) for f in fs]
    items = [(n.replace("\\", "/").lstrip("/"), o) for n, o in items]
    names = [n for n, _ in items]
    if (zipmode or strip) and names and all("/" in n for n in names) and len({n.split("/")[0] for n in names}) == 1:
        items = [(n.split("/", 1)[1], o) for n, o in items]
    if not items:
        raise ValueError("Файлы не выбраны")
    for n, opener in items:
        t = safe(base, n)
        if t == base:
            continue
        if t.is_dir():
            raise ValueError(f"{n}: на этом месте уже есть папка")
        t.parent.mkdir(parents=True, exist_ok=True)
        src = opener()
        with open(t, "wb") as out:
            shutil.copyfileobj(src, out)
        src.close()


def default_cmd(dest):
    for c in ("main.py", "app.py", "bot.py", "run.py"):
        if (dest / c).exists():
            return f"{{python}} {c}"
    py = sorted(p.name for p in dest.glob("*.py"))
    return f"{{python}} {py[0]}" if py else "{python} main.py"


def free_port():
    used = {m["port"] for m in meta.values()}
    p = 9001
    while p in used:
        p += 1
    return p


def err(msg, code=400):
    return jsonify(error=msg), code


def info(n):
    m, s = meta[n], st(n)
    p = s["p"]
    run = bool(p and p.poll() is None)
    return dict(name=n, command=m["command"], env=m.get("env", ""), port=m["port"], desired=m["desired"],
                running=run, pid=p.pid if run else None, uptime=int(time.time() - s["since"]) if run else 0,
                restarts=s["restarts"], code=s["code"],
                retry_in=max(0, int(s["next"] - time.time())) if m["desired"] and not run else 0,
                req=(PROJ / n / "requirements.txt").exists())


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=f"{e.code} {e.name}: {e.description}"), e.code
        return e
    app.logger.exception("Ошибка в %s", request.path)
    return jsonify(error=f"{type(e).__name__}: {e}"), 500


# ---------- авторизация ----------
LOGIN = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Вход</title><style>body{font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0;background:#eceff3;color:#14202e}
form{display:grid;gap:10px;width:260px}input,button{font:inherit;padding:10px;border:1px solid #c9d1db;border-radius:6px}
button{background:#2457d6;color:#fff;border:0;cursor:pointer}p{color:#c0392b;margin:0}</style>
<form method=post><b>Панель проектов</b><input type=password name=password placeholder="Пароль" autofocus>__ERR__<button>Войти</button></form>"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), PASSWORD):
            session.permanent = True
            session["ok"] = True
            return redirect("/")
        time.sleep(1)
        return LOGIN.replace("__ERR__", "<p>Неверный пароль</p>"), 401
    return LOGIN.replace("__ERR__", "")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.before_request
def guard():
    if request.endpoint in ("login", "static") or session.get("ok"):
        return None
    return (jsonify(error="auth"), 401) if request.path.startswith("/api/") else redirect("/login")


# ---------- API ----------
@app.get("/api/projects")
def list_projects():
    with lock:
        return jsonify([info(n) for n in sorted(meta)])


@app.post("/api/projects")
def create():
    name = request.form.get("name", "").strip().lower()
    if not NAME_RE.match(name):
        return err("Имя: латиница, цифры, - и _ (до 40 символов)")
    with lock:
        if name in meta:
            return err("Проект с таким именем уже есть")
        dest = PROJ / name
        try:
            dest.mkdir(parents=True, exist_ok=True)
            if any(f.filename for f in request.files.getlist("files")):
                deploy(dest, request.files.getlist("files"), strip=True)
        except Exception as e:
            shutil.rmtree(dest, ignore_errors=True)
            return err(f"{type(e).__name__}: {e}")
        meta[name] = dict(command=request.form.get("command", "").strip() or default_cmd(dest),
                          env="", port=free_port(), desired=False)
        save()
    return jsonify(ok=True)


@app.post("/api/projects/<n>/<action>")
def act(n, action):
    with lock:
        if n not in meta:
            return err("Нет такого проекта", 404)
        m, s = meta[n], st(n)
        if action in ("start", "restart"):
            kill(n)
            m["desired"], s["fails"], s["next"] = True, 0, 0
            spawn(n)
        elif action == "stop":
            m["desired"] = False
            kill(n)
        elif action == "delete":
            m["desired"] = False
            kill(n)
            shutil.rmtree(PROJ / n, ignore_errors=True)
            (LOGS / f"{n}.log").unlink(missing_ok=True)
            del meta[n]
            state.pop(n, None)
        elif action == "update":
            j = request.get_json(force=True)
            m["command"] = (j.get("command") or "").strip() or m["command"]
            m["env"] = j.get("env", "")
        elif action == "upload":
            fs = [f for f in request.files.getlist("files") if f.filename]
            if not fs:
                return err("Файлы не выбраны")
            try:
                deploy(PROJ / n, fs, strip=True)
            except (ValueError, zipfile.BadZipFile) as e:
                return err(str(e))
            if m["desired"]:
                kill(n)
                s["next"] = 0
                spawn(n)
        elif action == "clear":
            (LOGS / f"{n}.log").write_bytes(b"")
        else:
            return err("Неизвестное действие", 404)
        save()
    return jsonify(ok=True)


@app.get("/api/projects/<n>/logs")
def logs(n):
    if n not in meta:
        return err("Нет такого проекта", 404)
    p = LOGS / f"{n}.log"
    if not p.exists():
        return jsonify(text="")
    with open(p, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 200_000))
        data = f.read().decode("utf-8", "replace")
    return jsonify(text="\n".join(data.splitlines()[-400:]))


def ppath(n, rel=""):
    if n not in meta:
        abort(404)
    try:
        return safe(PROJ / n, rel)
    except ValueError:
        abort(400)


@app.get("/api/projects/<n>/files")
def files_ls(n):
    d = ppath(n, request.args.get("path", ""))
    if not d.is_dir():
        return err("Это не папка")
    root = (PROJ / n).resolve()
    es = [dict(name=x.name, dir=x.is_dir(), path=str(x.relative_to(root)),
               size=x.stat().st_size if x.is_file() else 0) for x in d.iterdir()]
    es.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return jsonify(entries=es)


@app.get("/api/projects/<n>/files/read")
def files_read(n):
    t = ppath(n, request.args.get("path", ""))
    if not t.is_file():
        return err("Файл не найден", 404)
    if t.stat().st_size > 1_000_000:
        return err("Файл больше 1 МБ, откройте его вручную по SSH")
    try:
        return jsonify(text=t.read_text("utf-8"))
    except UnicodeDecodeError:
        return err("Бинарный файл нельзя открыть в редакторе")


@app.get("/api/projects/<n>/files/download")
def files_download(n):
    t = ppath(n, request.args.get("path", ""))
    if not t.is_file():
        return err("Файл не найден", 404)
    return send_file(t, as_attachment=True, download_name=t.name)


@app.post("/api/projects/<n>/files/save")
def files_save(n):
    j = request.get_json(force=True)
    if not (j.get("path") or "").strip():
        return err("Укажите имя файла")
    t = ppath(n, j["path"].strip())
    if t.is_dir():
        return err("Это папка")
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_bytes(j.get("content", "").encode("utf-8"))
    return jsonify(ok=True)


@app.post("/api/projects/<n>/files/upload")
def files_upload(n):
    try:
        deploy(PROJ / n, request.files.getlist("files"), strip=False, sub=request.form.get("dir", ""))
    except (ValueError, zipfile.BadZipFile) as e:
        return err(str(e))
    return jsonify(ok=True)


@app.post("/api/projects/<n>/files/mkdir")
def files_mkdir(n):
    ppath(n, request.get_json(force=True).get("path", "")).mkdir(parents=True, exist_ok=True)
    return jsonify(ok=True)


@app.post("/api/projects/<n>/files/delete")
def files_delete(n):
    t = ppath(n, request.get_json(force=True).get("path", ""))
    if t == (PROJ / n).resolve():
        return err("Корень проекта удалить нельзя")
    shutil.rmtree(t) if t.is_dir() else t.unlink(missing_ok=True)
    return jsonify(ok=True)


@app.post("/api/pip")
def pip():
    j = request.get_json(force=True)
    if j.get("project"):
        req = PROJ / j["project"] / "requirements.txt"
        if j["project"] not in meta or not req.exists():
            return err("requirements.txt не найден")
        args = ["-r", str(req)]
    else:
        args = shlex.split(j.get("packages", ""))
    if not args:
        return err("Укажите пакеты")
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", *args], capture_output=True, text=True, timeout=850)
    except subprocess.TimeoutExpired:
        return err("pip завис дольше 14 минут")
    return jsonify(ok=r.returncode == 0, output=(r.stdout + r.stderr)[-6000:])


@app.get("/")
def index():
    return PAGE


PAGE = r"""<!doctype html><html lang=ru><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Панель проектов</title>
<style>
:root{--bg:#eceff3;--panel:#fff;--ink:#14202e;--mute:#66758a;--line:#c9d1db;--acc:#2457d6;--ok:#1f8a4c;--bad:#c0392b}
@media(prefers-color-scheme:dark){:root{--bg:#10161e;--panel:#18212c;--ink:#e3e9f0;--mute:#8b9aad;--line:#2b3846;--acc:#6b95ff;--ok:#3fb976;--bad:#ef6b5b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:20px 16px 60px}
header{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:18px}header h1{font-size:20px;margin:0 auto 0 0}
button,input,textarea{font:inherit;color:inherit}
button{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 12px;cursor:pointer}
button:hover{border-color:var(--acc)}button.p{background:var(--acc);border-color:var(--acc);color:#fff}button.d{color:var(--bad)}
button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
a{color:var(--mute)}
#list{background:var(--panel);border:1px solid var(--line);border-radius:8px}
.row{display:flex;gap:12px;align-items:center;padding:12px 14px;border-top:1px solid var(--line);flex-wrap:wrap}
.row:first-child{border-top:0}.row.sel{background:color-mix(in srgb,var(--acc) 8%,transparent)}
.dot{width:10px;height:10px;border-radius:50%;background:var(--mute);flex:none}.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}
.info{flex:1;min-width:200px}.info b{font-size:16px}.info small{display:block;color:var(--mute)}
.btns{display:flex;gap:6px;flex-wrap:wrap}.fr{display:flex;gap:10px;align-items:center;padding:7px 10px;border-top:1px solid var(--line);cursor:pointer}.fr:first-child{border-top:0}.fr:hover{background:var(--bg)}.fr span{flex:1;word-break:break-all}.fr small{color:var(--mute)}.fr button{padding:0 8px}
.empty{padding:28px;color:var(--mute);text-align:center}
#logbox{margin-top:16px;display:none}#logbox .h{display:flex;gap:8px;align-items:center;margin-bottom:6px}#logbox .h b{margin-right:auto}
pre{margin:0;background:#0d131a;color:#d5dde6;border-radius:8px;padding:12px;font:13px/1.4 ui-monospace,monospace;overflow:auto;max-height:420px;white-space:pre-wrap;word-break:break-all}
dialog{border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--ink);width:min(520px,94vw);padding:20px}
dialog::backdrop{background:#0008}dialog form,dialog .f{display:grid;gap:10px}
label{display:grid;gap:4px;color:var(--mute);font-size:13px}
input,textarea{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;width:100%}
textarea{min-height:80px;font-family:ui-monospace,monospace;font-size:13px}.acts{display:flex;gap:8px;justify-content:flex-end;margin-top:6px}
</style>
<main>
<header><h1>Панель проектов</h1><button id=bPip>Пакеты (pip)</button><button class=p id=bNew>Новый проект</button><a href=/logout>Выйти</a></header>
<div id=list></div>
<section id=logbox><div class=h><b id=logTitle></b><button id=bClear>Очистить</button><button id=bClose>Закрыть</button></div><pre id=log></pre></section>
</main>

<dialog id=dNew><form id=fNew>
<b>Новый проект</b>
<label>Имя<input name=name required pattern="[a-z0-9][a-z0-9_\-]*" placeholder="my-bot"></label>
<label>Файлы проекта: несколько файлов или один .zip<input type=file id=nFiles multiple></label>
<label>Или целая папка (с вложенными папками)<input type=file id=nDir webkitdirectory></label>
<label>Команда запуска (необязательно)<input name=command placeholder="{python} main.py"></label>
<small style="color:var(--mute)">{python} — python из общего venv, {port} — порт проекта (он же в переменной PORT). Для Flask: gunicorn -b 127.0.0.1:{port} app:app</small>
<div class=acts><button type=button onclick="dNew.close()">Отмена</button><button class=p>Создать</button></div></form></dialog>

<dialog id=dSet><div class=f>
<b id=setTitle></b>
<label>Команда запуска<input id=sCmd></label>
<label>Переменные окружения (KEY=value, по одной в строке)<textarea id=sEnv></textarea></label>
<label>Обновить код: файлы или .zip (совпадающие файлы перезапишутся)<input type=file id=sFiles multiple></label>
<label>Или папка целиком<input type=file id=sDir webkitdirectory></label>
<div class=acts><button class=d id=sDel style="margin-right:auto">Удалить проект</button><button onclick="dSet.close()">Отмена</button><button class=p id=sSave>Сохранить</button></div></div></dialog>

<dialog id=dPip><div class=f>
<b>Общий venv: установка пакетов</b>
<label>Пакеты<input id=pPk placeholder="flask requests gunicorn"></label>
<div class=acts><button id=pReq>Из requirements.txt проекта…</button><button class=p id=pGo>Установить</button></div>
<pre id=pOut style="display:none;max-height:260px"></pre>
<div class=acts><button onclick="dPip.close()">Закрыть</button></div></div></dialog>

<dialog id=dFiles style="width:min(640px,96vw)"><div class=f>
<b id=fTitle></b>
<div id=fBrowse class=f>
<code id=fPath></code>
<div id=fList style="border:1px solid var(--line);border-radius:6px;max-height:320px;overflow:auto"></div>
<input type=file id=fUp multiple hidden><input type=file id=fUpDir webkitdirectory hidden>
<div class=btns><button onclick="fUp.click()">Загрузить файлы</button><button onclick="fUpDir.click()">Загрузить папку</button><button id=bMk>Новая папка</button><button id=bNewFile>Новый файл</button></div>
</div>
<div id=fEd class=f style="display:none"><input id=eName placeholder="путь/к/файлу.py"><textarea id=eText spellcheck=false style="min-height:320px"></textarea>
<div class=acts><button id=eDl style="margin-right:auto">Скачать</button><button id=eBack>Назад</button><button class=p id=eSave>Сохранить</button></div></div>
<small style="color:var(--mute)">Изменения вступают в силу после перезапуска проекта. Один .zip распаковывается в текущую папку.</small>
<div class=acts><button onclick="dFiles.close()">Закрыть</button></div></div></dialog>

<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let data=[],openLog=null,cur=null;
async function api(u,o){const r=await fetch(u,o);if(r.status==401){location='/login';throw 0}
 const j=await r.json().catch(()=>({}));if(!r.ok){alert(j.error||r.statusText);throw new Error(j.error)}return j}
const post=(u,b)=>api(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});
const form=(u,fd)=>api(u,{method:'POST',body:fd});
function dur(s){const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return d?`${d}д ${h}ч`:h?`${h}ч ${m}м`:m?`${m}м`:`${s}с`}
function status(p){
 if(p.running)return['ok',`работает ${dur(p.uptime)}`];
 if(p.desired)return['bad',p.code!=null?`упал (код ${p.code}), перезапуск через ${p.retry_in}с`:'запускается'];
 return['',p.code!=null?`остановлен (код ${p.code})`:'остановлен']}
function render(){
 $('#list').innerHTML=data.length?data.map(p=>{const[c,t]=status(p);return`<div class="row ${p.name==openLog?'sel':''}">
 <span class="dot ${c}"></span><div class=info><b>${esc(p.name)}</b><small>${t} · порт ${p.port} · перезапусков ${p.restarts}</small><small>${esc(p.command)}</small></div>
 <div class=btns data-n="${esc(p.name)}">${p.running?'<button data-a=stop>Стоп</button><button data-a=restart>Перезапуск</button>':'<button class=p data-a=start>Запуск</button>'}
 <button data-a=files>Файлы</button><button data-a=logs>Логи</button><button data-a=set>Настройки</button></div></div>`}).join(''):'<div class=empty>Проектов пока нет. Нажмите «Новый проект».</div>'}
async function refresh(){data=await api('/api/projects');render();if(openLog)loadLog()}
async function loadLog(){const{text}=await api(`/api/projects/${openLog}/logs`);const el=$('#log');
 const stick=el.scrollHeight-el.scrollTop-el.clientHeight<40;el.textContent=text||'(лог пуст)';if(stick)el.scrollTop=el.scrollHeight}
$('#list').onclick=async e=>{const b=e.target.closest('button[data-a]');if(!b)return;const n=b.parentNode.dataset.n,a=b.dataset.a;
 if(a=='logs'){openLog=n;$('#logTitle').textContent='Лог: '+n;$('#logbox').style.display='block';await loadLog();$('#log').scrollTop=1e9;render()}
 else if(a=='set'){cur=data.find(p=>p.name==n);$('#setTitle').textContent=n;$('#sCmd').value=cur.command;$('#sEnv').value=cur.env;$('#sFiles').value='';$('#sDir').value='';dSet.showModal()}
 else if(a=='files')openFiles(n);
 else{await post(`/api/projects/${n}/${a}`);refresh()}};
$('#bClose').onclick=()=>{openLog=null;$('#logbox').style.display='none';render()};
$('#bClear').onclick=async()=>{await post(`/api/projects/${openLog}/clear`);loadLog()};
$('#bNew').onclick=()=>{$('#fNew').reset();dNew.showModal()};
$('#fNew').onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target);addFiles(fd,'#nFiles','#nDir');await form('/api/projects',fd);dNew.close();refresh()};
$('#sSave').onclick=async()=>{const n=cur.name;await post(`/api/projects/${n}/update`,{command:$('#sCmd').value,env:$('#sEnv').value});
 const fd=new FormData();addFiles(fd,'#sFiles','#sDir');if(fd.has('files'))await form(`/api/projects/${n}/upload`,fd);
 dSet.close();if(cur.running)await post(`/api/projects/${n}/restart`);refresh()};
$('#sDel').onclick=async()=>{if(confirm(`Удалить «${cur.name}» вместе с файлами?`)){await post(`/api/projects/${cur.name}/delete`);dSet.close();if(openLog==cur.name)$('#bClose').click();refresh()}};
$('#bPip').onclick=()=>{$('#pOut').style.display='none';dPip.showModal()};
async function pip(body,btn){btn.disabled=true;const o=$('#pOut');o.style.display='block';o.textContent='Устанавливаю…';
 try{const r=await post('/api/pip',body);o.textContent=(r.ok?'Готово.\n\n':'Ошибка.\n\n')+r.output}catch(e){o.textContent='Ошибка: '+e.message}btn.disabled=false}
$('#pGo').onclick=e=>pip({packages:$('#pPk').value},e.target);
$('#pReq').onclick=e=>{const c=data.filter(p=>p.req).map(p=>p.name);if(!c.length)return alert('Ни в одном проекте нет requirements.txt');
 const n=c.length==1?c[0]:prompt('Какой проект? '+c.join(', '),c[0]);if(n)pip({project:n},e.target)};
function addFiles(fd,...sel){for(const s of sel)for(const f of $(s).files)fd.append('files',f,f.webkitRelativePath||f.name)}
const fmtSize=b=>b>1048576?(b/1048576).toFixed(1)+' МБ':b>1024?Math.round(b/1024)+' КБ':b+' Б';
let fn=null,fp='';
const j=(a,p)=>`/api/projects/${fn}/files${a}?path=${encodeURIComponent(p)}`;
function view(ed){$('#fEd').style.display=ed?'grid':'none';$('#fBrowse').style.display=ed?'none':'grid'}
async function openFiles(n){fn=n;fp='';$('#fTitle').textContent='Файлы проекта '+n;view(false);dFiles.showModal();await ls()}
async function ls(){const r=await api(j('',fp));$('#fPath').textContent='/'+fp;
 $('#fList').innerHTML=(fp?'<div class=fr data-k=up><span>..</span></div>':'')+(r.entries.map(e=>`<div class=fr data-k=${e.dir?'d':'f'} data-p="${esc(e.path)}"><span>${esc(e.name)}${e.dir?'/':''}</span><small>${e.dir?'':fmtSize(e.size)}</small>${e.dir?'':'<button data-k=dl title="Скачать">Скачать</button>'}<button class=d data-k=del title="Удалить">×</button></div>`).join('')||(fp?'':'<div class=empty>Папка пуста</div>'))}
$('#fList').onclick=async e=>{const r=e.target.closest('.fr');if(!r)return;
 if(e.target.dataset.k=='dl'){location=j('/download',r.dataset.p);return}
 if(e.target.dataset.k=='del'){if(confirm('Удалить '+r.dataset.p+'?')){await post(`/api/projects/${fn}/files/delete`,{path:r.dataset.p});ls()}return}
 if(r.dataset.k=='up'){fp=fp.split('/').slice(0,-1).join('/');ls()}
 else if(r.dataset.k=='d'){fp=r.dataset.p;ls()}
 else{const t=await api(j('/read',r.dataset.p));$('#eName').value=r.dataset.p;$('#eText').value=t.text;view(true)}};
$('#bNewFile').onclick=()=>{$('#eName').value=fp?fp+'/':'';$('#eText').value='';view(true)};
$('#eBack').onclick=()=>view(false);
$('#eDl').onclick=()=>{location=j('/download',$('#eName').value.trim())};
$('#eSave').onclick=async()=>{await post(`/api/projects/${fn}/files/save`,{path:$('#eName').value,content:$('#eText').value});view(false);ls()};
$('#bMk').onclick=async()=>{const n=prompt('Имя папки');if(n){await post(`/api/projects/${fn}/files/mkdir`,{path:(fp?fp+'/':'')+n});ls()}};
for(const id of['#fUp','#fUpDir'])$(id).onchange=async()=>{const fd=new FormData();fd.append('dir',fp);addFiles(fd,id);await form(`/api/projects/${fn}/files/upload`,fd);$(id).value='';ls()};
refresh();setInterval(refresh,3000);
</script></html>"""
