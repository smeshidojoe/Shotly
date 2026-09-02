import os
import sys

APP_NAME    = "Shotly"
APP_VERSION = "0.1.3"

GITHUB_REPO   = "SmeshidoJoe/Shotly"
DEVELOPER_URL = "https://github.com/SmeshidoJoe"

# Идентификатор для Windows: под ним группируются уведомления и панель задач.
APP_ID = "SmeshidoJoe.Shotly"

# Именованный мьютекс защиты от второго запуска (см. main.py и .iss).
INSTANCE_MUTEX = "Shotly-Single-Instance-Mutex"

# В сборке PyInstaller ресурсы лежат во временной папке _MEIPASS, в разработке —
# в корне репозитория. Папку установки exe берём отдельно (core/updater.py).
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ASSETS_DIR = os.path.join(BASE_DIR, "assets")
APP_ICO    = os.path.join(ASSETS_DIR, "app.ico")

# Пользовательские данные — в %APPDATA%\Shotly (запасной путь для не-Windows).
_BASE = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
APP_DIR = os.path.join(_BASE, APP_NAME)

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
CRASH_LOG   = os.path.join(APP_DIR, "crash.log")

# Куда сохранять по умолчанию: ~/Pictures/Shotly.
def default_save_dir():
    pics = os.path.join(os.path.expanduser("~"), "Pictures")
    if not os.path.isdir(pics):
        pics = os.path.expanduser("~")
    return os.path.join(pics, APP_NAME)


# --- Оформление ------------------------------------------------------------ #
ACCENT       = "#4f8cff"     # фирменный синий: рамка выделения, активные пункты
DIM_ALPHA    = 150           # затемнение экрана вне выделения (0..255)
HANDLE_SIZE  = 7             # сторона квадратика-ручки на рамке выделения
TOOLBAR_BTN  = 26            # сторона кнопки на панелях инструментов
TOOLBAR_PAD  = 4
