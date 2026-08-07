"""
Веб-терминал на основе pty (Python pseudo-terminal) + xterm.js на фронтенде.

Важно: доступ к терминалу защищён обычной сессией Flask-Login (тот же логин,
что и в панель). Никакие SSH-логины/пароли нигде не используются и не хранятся —
процесс bash запускается локально на этой же машине под тем же пользователем,
что и сама панель.
"""
import fcntl
import os
import pty
import select
import struct
import subprocess
import termios

from flask_login import current_user
from flask_socketio import Namespace, emit

# session_id -> {"fd": int, "pid": int}
_sessions = {}


def _set_winsize(fd, rows, cols):
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


class TerminalNamespace(Namespace):
    def on_connect(self):
        if not current_user.is_authenticated:
            return False

    def on_start(self, data):
        cwd = data.get("cwd") or os.path.expanduser("~")
        sid = self.get_sid_ns()

        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(cwd)
            os.execvp("bash", ["bash"])
        else:
            _sessions[sid] = {"fd": fd, "pid": pid}
            self.start_background_task(sid, fd)
            emit("ready")

    def get_sid_ns(self):
        from flask import request
        return request.sid

    def start_background_task(self, sid, fd):
        from .extensions import socketio

        def read_loop():
            while True:
                try:
                    r, _, _ = select.select([fd], [], [], 1)
                except (OSError, ValueError):
                    break
                if fd in r:
                    try:
                        data = os.read(fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    socketio.emit(
                        "output", data.decode(errors="replace"),
                        namespace="/terminal", to=sid,
                    )
        socketio.start_background_task(read_loop)

    def on_input(self, data):
        sid = self.get_sid_ns()
        sess = _sessions.get(sid)
        if sess:
            os.write(sess["fd"], data.encode())

    def on_resize(self, data):
        sid = self.get_sid_ns()
        sess = _sessions.get(sid)
        if sess:
            _set_winsize(sess["fd"], data.get("rows", 24), data.get("cols", 80))

    def on_disconnect(self):
        sid = self.get_sid_ns()
        sess = _sessions.pop(sid, None)
        if sess:
            try:
                os.close(sess["fd"])
                os.kill(sess["pid"], 9)
            except (OSError, ProcessLookupError):
                pass
