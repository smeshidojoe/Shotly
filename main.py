"""
Точка входа Shotly.
"""

import os
import signal
import sys

# Масштабирование Qt выключаем ДО импорта QtWidgets: оверлею нужны физические
# пиксели один в один со снимком, иначе на мониторе со 125–200% рамка выделения
# и картинка разъезжаются. Размеры окон программа масштабирует сама (ui/theme.py).
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QTimer                    # noqa: E402
from PySide6.QtWidgets import QApplication           # noqa: E402

from shotly.app import App                           # noqa: E402
from shotly.core import crashlog, updater            # noqa: E402
from shotly.core.constants import APP_ID, APP_NAME   # noqa: E402
from shotly.core.single import SingleInstance        # noqa: E402
from shotly.tray import Tray                         # noqa: E402


def _set_app_identity(app):
    """Имя для ОС: под ним группируются уведомления и значок в панели задач."""
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _install_console_interrupt(app, controller):
    """Ctrl+C в консоли должен закрывать программу, а не висеть.

    Qt-цикл событий не отдаёт управление интерпретатору, поэтому обработчик
    сигнала не вызывается, пока не случится Python-код: таймер-пульс раз в
    четверть секунды даёт эту возможность. Стоит копейки и живёт только для
    запуска из консоли — в собранном exe консоли нет, но и вреда от него нет.
    """
    def handler(_signum, _frame):
        print("\nShotly: interrupted, quitting...", file=sys.stderr)
        controller.quit()

    for name in ("SIGINT", "SIGBREAK", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass                        # не главный поток или сигнал не поддержан

    pulse = QTimer(app)
    pulse.timeout.connect(lambda: None)
    pulse.start(250)
    return pulse


def main():
    # Самоприменение обновления: этот же exe запущен новой версией с флагом
    # --apply-update <старый exe>. Обрабатываем ДО мьютекса — это не второй
    # экземпляр в обычном смысле.
    if "--apply-update" in sys.argv:
        try:
            i = sys.argv.index("--apply-update")
            updater.apply_self_update(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
        except Exception:
            pass
        return 0

    # В собранном exe stdout никуда не ведёт — без хука traceback пропал бы.
    crashlog.install()
    crashlog.cleanup()

    app = QApplication(sys.argv)
    _set_app_identity(app)
    app.setQuitOnLastWindowClosed(False)      # программа живёт в трее

    # Второй запуск не плодит иконку в трее, а просит первый снять скриншот:
    # иначе повторный клик по ярлыку выглядел бы как «ничего не произошло».
    instance = SingleInstance(app)
    if not instance.is_first():
        SingleInstance.wake_running()
        return 0

    # Страховка: остался распакованный апдейт — применяем, что не заблокировано.
    try:
        updater.apply_pending_update()
        updater.cleanup_applied()
    except Exception:
        pass

    controller = App()
    tray = Tray(controller)
    controller.tray = tray
    tray.run()

    instance.woken.connect(controller.start_capture)
    instance.listen()
    app.aboutToQuit.connect(instance.close)

    _install_console_interrupt(app, controller)

    controller.sync_autostart()
    controller.check_updates_async()
    controller.run_first_launch()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
