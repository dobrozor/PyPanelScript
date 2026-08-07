import sqlite3
from contextlib import contextmanager

from . import config


def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db_session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                totp_secret TEXT,
                totp_enabled INTEGER DEFAULT 0,
                failed_attempts INTEGER DEFAULT 0,
                locked_until TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                entry_file TEXT DEFAULT 'main.py',
                args TEXT DEFAULT '',
                env_json TEXT DEFAULT '{}',
                autostart INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                cron_expr TEXT NOT NULL,
                enabled INTEGER DEFAULT 1
            )
            """
        )
