# Python Hosting Panel

Панель управления Python-проектами на вашем собственном сервере: создание
проектов, запуск/остановка через `systemd`, файловый менеджер с редактором
кода (Monaco), встроенный веб-терминал, логи в реальном времени, установка
зависимостей, Git, бэкапы и планировщик задач.

Полностью самостоятельный проект — панель работает **локально на сервере**
и не запрашивает и не хранит никакие SSH-логины/пароли. Веб-терминал
реализован через `pty` + `xterm.js`, поэтому подключение "по SSH к самому
себе" не требуется.

## Возможности

- Создание/удаление/импорт Python-проектов
- Управление через systemd: start / stop / restart / enable / disable
- Статус (🟢 работает / 🔴 остановлен), PID, CPU/RAM, число потоков
- Логи в реальном времени с автообновлением и фильтром
- Файловый менеджер (создание папок/файлов, переименование, удаление,
  загрузка, скачивание) + редактор Monaco (подсветка, автосохранение,
  поиск, сворачивание кода)
- Веб-терминал (bash) прямо в браузере
- Установка библиотек из `requirements.txt` или вручную — в общий venv
  (`bots/venv`), тот же, что использует сама панель и который вы можете
  активировать вручную через `source bots/venv/bin/activate`
- Git: init / commit / push / pull
- Мониторинг CPU/RAM/диска сервера и каждого проекта
- Резервное копирование в `.tar.gz` с восстановлением в один клик
- Планировщик через systemd timers (каждые 5 минут / час / день)
- Глобальный поиск по файлам и содержимому проектов
- Тёмная/светлая тема, адаптивный интерфейс
- Логин + хэш пароля (werkzeug), защита от CSRF, лимит попыток входа,
  автоматический выход по бездействию, опциональная 2FA (TOTP)

## Стек

- **Backend:** Flask, Flask-Login, Flask-SocketIO, Flask-WTF (CSRF)
- **Frontend:** ванильный JS + Monaco Editor + xterm.js
- **Реалтайм:** WebSocket (Flask-SocketIO + eventlet)
- **Хранение:** SQLite (пользователи, проекты) + файловая система
- **Процессы:** systemd (unit-файлы `panelbot-<project>.service`)

## Требования

- Ubuntu/Debian сервер с root-доступом (для управления systemd)
- Python 3.10+
- nginx (рекомендуется, для TLS и reverse-proxy)

## Файлы, которые нужно положить в GitHub

В репозиторий кладите **весь код**, кроме того, что генерируется на сервере
(это уже настроено в `.gitignore`):

```
✅ В git:                          ❌ НЕ в git (создаётся на сервере):
run.py                             venv/            (общий venv)
requirements.txt                   panel.db         (база пользователей)
panel/  (весь код)                 projects/        (файлы ваших ботов)
deploy/ (install.sh, update.sh,    systemd/         (копии unit-файлов)
         panel.service,            backups/         (архивы бэкапов)
         nginx.conf.example)       logs/            (логи проектов)
README.md
.gitignore
```

То есть просто закоммитьте содержимое архива как есть — `.gitignore`
уже исключает папки с данными сервера, они и не попадут в репозиторий.

```bash
cd pypanel
git init
git add .
git commit -m "Python Hosting Panel"
git branch -M main
git remote add origin https://github.com/ваш-логин/ваш-репозиторий.git
git push -u origin main
```

## Установка на сервер (один раз)

Скачиваем только сам скрипт установки (репозиторий ещё не клонирован)
и передаём ему ссылку на ваш репозиторий:

```bash
curl -fsSL https://raw.githubusercontent.com/ваш-логин/ваш-репозиторий/main/deploy/install.sh -o install.sh
bash install.sh https://github.com/ваш-логин/ваш-репозиторий.git
```

Скрипт клонирует репозиторий в `/root/bots`, создаёт общий venv,
ставит зависимости, генерирует `SECRET_KEY` и запускает `panel.service`.

## Обновление кода на сервере (после установки)

Как только что-то поменяли в коде и запушили в GitHub — на сервере одна команда:

```bash
bash /root/bots/deploy/update.sh
```

Она делает `git pull`, обновляет зависимости и перезапускает `panel.service`.

## Запуск вручную (для разработки)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

Панель будет доступна на `http://127.0.0.1:8000`.

## Важные замечания по безопасности

- Панель должна работать за nginx с HTTPS — не открывайте порт 8000 наружу напрямую.
- Панель запускается от `root` (или пользователя с правами `sudo systemctl`
  без пароля на конкретные unit-ы), так как ей нужно управлять systemd —
  ограничьте доступ к серверу и держите панель за VPN/файрволом, если это
  дополнительно возможно.
- Включите 2FA в настройках безопасности после первого входа.
- Регулярно обновляйте зависимости (`pip list --outdated`).

## Структура проекта

```
pypanel/
├── run.py                  # точка входа
├── requirements.txt
├── deploy/
│   ├── install.sh
│   ├── panel.service        # systemd unit для самой панели
│   └── nginx.conf.example
└── panel/
    ├── __init__.py          # фабрика приложения
    ├── config.py
    ├── db.py                 # SQLite
    ├── auth.py                # пользователи, пароли, 2FA
    ├── routes.py              # все HTTP/JSON-маршруты
    ├── systemd_manager.py     # start/stop/restart/status через systemctl
    ├── file_manager.py        # безопасный файловый менеджер (без path traversal)
    ├── pip_manager.py         # venv + requirements.txt
    ├── monitor.py             # CPU/RAM через psutil
    ├── backup_manager.py      # tar.gz бэкапы
    ├── git_manager.py         # git init/commit/push/pull
    ├── scheduler.py           # systemd timers
    ├── terminal.py            # веб-терминал через pty + SocketIO
    ├── extensions.py          # login_manager, socketio
    ├── templates/
    └── static/{css,js}
```

Проекты пользователей хранятся в `/root/bots/projects/<name>/`, их
systemd-юниты — `panelbot-<name>.service`, логи — `/root/bots/logs/<name>.log`.

## Общий venv

Все проекты и сама панель используют **один общий venv** —
`/root/bots/venv` (тот, что создаёт `install.sh` и который вы активируете
вручную через `source bots/venv/bin/activate`). Отдельный venv на каждый
проект не создаётся.

- Кнопка «Установить зависимости» в проекте ставит пакеты из его
  `requirements.txt` именно в этот общий venv.
- Systemd-юниты проектов запускают код через
  `/root/bots/venv/bin/python`.
- Если нужно использовать venv по другому пути, задайте переменную
  окружения `PANEL_SHARED_VENV` (например, в `panel.service`):
  ```
  Environment="PANEL_SHARED_VENV=/root/bots/venv"
  ```
