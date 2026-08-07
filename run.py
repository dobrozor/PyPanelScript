import eventlet
eventlet.monkey_patch()

from panel import create_app
from panel.extensions import socketio

app = create_app()

if __name__ == "__main__":
    # host 127.0.0.1 + nginx reverse-proxy с TLS — рекомендуемая схема для продакшена.
    # Для быстрой проверки можно временно указать host="0.0.0.0", но тогда обязательно
    # закройте порт файрволом и включите HTTPS.
    socketio.run(app, host="127.0.0.1", port=8000, debug=False)
