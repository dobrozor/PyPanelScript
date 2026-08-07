import os

from flask import Flask
from flask_wtf import CSRFProtect

from . import config
from .auth import User
from .db import init_db
from .extensions import login_manager, socketio


csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
    # сессия завершается через 30 минут бездействия
    app.config["PERMANENT_SESSION_LIFETIME"] = 1800
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    init_db()

    login_manager.init_app(app)
    login_manager.login_view = "main.login"

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(user_id)

    csrf.init_app(app)
    socketio.init_app(app, async_mode="eventlet")

    from .routes import bp as main_bp
    app.register_blueprint(main_bp)

    from .terminal import TerminalNamespace
    socketio.on_namespace(TerminalNamespace("/terminal"))

    @app.before_request
    def make_session_permanent():
        from flask import session
        session.permanent = True

    return app
