r"""
Перехват необработанных исключений.

В собранном exe stdout никуда не ведёт, и traceback исчезает бесследно.
Ставим хук ДО QApplication, пишем в %APPDATA%\Shotly\crash.log.

Перехватчиков два: главный поток (sys.excepthook) и обычные потоки
(threading.excepthook) — проверка обновлений и регистрация горячих клавиш живут
как раз в потоках, и там исключение иначе умирает молча.
"""

import os
import sys
import threading
import time
import traceback

from .constants import APP_DIR, APP_VERSION, CRASH_LOG

_MAX_BYTES = 256 * 1024

# Управляющие исключения — это не падения программы. KeyboardInterrupt здесь
# особенно важен: при запуске из консоли Ctrl+C — штатный способ выйти, и писать
# на него отчёт о падении незачем.
_NOT_A_CRASH = (KeyboardInterrupt, SystemExit, GeneratorExit)


def _is_crash(exc_type):
    return not (isinstance(exc_type, type) and issubclass(exc_type, _NOT_A_CRASH))


def _write(exc_type, exc, tb, where):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write("\n--- %s  v%s  (%s) ---\n"
                    % (time.strftime("%Y-%m-%d %H:%M:%S"), APP_VERSION, where))
            traceback.print_exception(exc_type, exc, tb, file=f)
    except OSError:
        pass


def install():
    prev = sys.excepthook

    def hook(exc_type, exc, tb):
        if _is_crash(exc_type):
            _write(exc_type, exc, tb, "main")
        if prev is not None:
            prev(exc_type, exc, tb)

    sys.excepthook = hook

    def thread_hook(args):
        if _is_crash(args.exc_type):
            _write(args.exc_type, args.exc_value, args.exc_traceback,
                   getattr(args.thread, "name", "thread"))

    threading.excepthook = thread_hook


def cleanup():
    """Не даём логу расти бесконечно: слишком большой просто удаляем."""
    try:
        if os.path.getsize(CRASH_LOG) > _MAX_BYTES:
            os.remove(CRASH_LOG)
    except OSError:
        pass
