import datetime as dt

import pyotp
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .db import db_session

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.username = row["username"]
        self.password_hash = row["password_hash"]
        self.totp_secret = row["totp_secret"]
        self.totp_enabled = bool(row["totp_enabled"])
        self.failed_attempts = row["failed_attempts"]
        self.locked_until = row["locked_until"]

    @staticmethod
    def get_by_id(user_id):
        with db_session() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return User(row) if row else None

    @staticmethod
    def get_by_username(username):
        with db_session() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return User(row) if row else None

    @staticmethod
    def count():
        with db_session() as conn:
            return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

    @staticmethod
    def create(username, password):
        pw_hash = generate_password_hash(password)
        with db_session() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, pw_hash),
            )

    def is_locked(self):
        if not self.locked_until:
            return False
        return dt.datetime.fromisoformat(self.locked_until) > dt.datetime.utcnow()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def register_failed_attempt(self):
        attempts = self.failed_attempts + 1
        locked_until = None
        if attempts >= MAX_FAILED_ATTEMPTS:
            locked_until = (
                dt.datetime.utcnow() + dt.timedelta(minutes=LOCKOUT_MINUTES)
            ).isoformat()
            attempts = 0
        with db_session() as conn:
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                (attempts, locked_until, self.id),
            )

    def reset_failed_attempts(self):
        with db_session() as conn:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
                (self.id,),
            )

    def set_password(self, password):
        with db_session() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), self.id),
            )

    def enable_totp(self, secret):
        with db_session() as conn:
            conn.execute(
                "UPDATE users SET totp_secret = ?, totp_enabled = 1 WHERE id = ?",
                (secret, self.id),
            )

    def disable_totp(self):
        with db_session() as conn:
            conn.execute(
                "UPDATE users SET totp_secret = NULL, totp_enabled = 0 WHERE id = ?",
                (self.id,),
            )

    def verify_totp(self, code):
        if not self.totp_secret:
            return False
        return pyotp.TOTP(self.totp_secret).verify(code, valid_window=1)
