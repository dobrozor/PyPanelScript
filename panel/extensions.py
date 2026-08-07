from flask_login import LoginManager
from flask_socketio import SocketIO

login_manager = LoginManager()
socketio = SocketIO(cors_allowed_origins="*")
