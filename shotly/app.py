"""
Управляющий объект приложения: настройки, горячие клавиши, оверлей съёмки,
окна настроек и «О программе».

Окна тут не хранятся дольше, чем нужно: настройки пересоздаются при каждом
открытии — иначе после смены языка окно осталось бы на старом.
"""

import os
import threading

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFileDialog

from .core import autostart, capture, config, i18n, saver, updater
from .core.constants import APP_NAME, CONFIG_PATH, IS_FIRST_RUN
from .core.hotkey import HotkeyManager, pretty
from .core.i18n import tr
from .ui import theme, toast
from .ui.about import AboutWindow
from .ui.overlay import Overlay
from .ui.settings_window import SettingsWindow

_FILTERS = {
    "png": "PNG (*.png)",
    "jpg": "JPEG (*.jpg *.jpeg)",
    "bmp": "BMP (*.bmp)",
}


class App(QObject):
    update_found = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = config.load()
        i18n.set_language(self.settings.get("language", "ru"))

        self.tray = None
        self._overlay = None
        self._settings_win = None
        self._about_win = None
        self._last_selection = None       # QRect в координатах экрана

        self.hotkeys = HotkeyManager(self)
        self.hotkeys.capture.connect(self.start_capture)
        self.hotkeys.full_save.connect(self.capture_full_save)
        self.hotkeys.full_copy.connect(self.capture_full_copy)
        self.hotkeys.apply(self.settings)

        self.update_found.connect(self._on_update_found)

    # ------------------------------------------------------------------ #
    #  Съёмка
    # ------------------------------------------------------------------ #
    def start_capture(self):
        """Основной сценарий: снимок экрана -> оверлей с выделением."""
        if self._overlay is not None:
            # Повторное нажатие хоткея при открытом оверлее — просто фокус на него.
            self._overlay.raise_()
            self._overlay.activateWindow()
            return

        # Окна программы не должны попасть в кадр.
        for win in (self._settings_win, self._about_win):
            if win is not None and win.isVisible():
                win.hide()

        theme.invalidate_scale()          # курсор мог переехать на другой монитор
        shot = capture.grab(self.settings.get("capture_cursor", False))
        if shot is None or shot.isNull():
            self._toast(tr("Nothing to capture"), icon_name="info")
            return

        origin = capture.virtual_rect().topLeft()
        overlay = Overlay(shot, origin, self.settings)
        overlay.copy_requested.connect(self._on_copy)
        overlay.save_requested.connect(self._on_save)
        overlay.print_requested.connect(self._on_print)
        overlay.closed.connect(self._on_overlay_closed)
        self._overlay = overlay

        initial = self._last_selection if self.settings.get(
            "remember_selection") else None
        overlay.start(initial)

    def capture_full_save(self):
        """Быстрое сохранение всего экрана — без оверлея и вопросов."""
        shot = capture.grab(self.settings.get("capture_cursor", False))
        if shot is None or shot.isNull():
            return
        path = saver.default_path(self.settings)
        if saver.save_pixmap(shot, path, self.settings):
            if self.settings.get("copy_after_save"):
                saver.copy_to_clipboard(shot)
            self._toast(tr("Saved"), os.path.basename(path), open_path=path)
        else:
            self._toast(tr("Save failed"), icon_name="info")

    def capture_full_copy(self):
        shot = capture.grab(self.settings.get("capture_cursor", False))
        if shot is None or shot.isNull():
            return
        if saver.copy_to_clipboard(shot):
            self._toast(tr("Copied to clipboard"), icon_name="copy")

    # --- результаты оверлея --------------------------------------------- #
    def _on_copy(self, pixmap):
        saver.copy_to_clipboard(pixmap)
        self._toast(tr("Copied to clipboard"), icon_name="copy")
        self._finish_overlay()

    def _on_save(self, pixmap):
        overlay = self._overlay
        if overlay is not None:
            # Диалог поверх оверлея: оверлей всегда наверху, и системное окно
            # оказалось бы под ним. Прячем оверлей на время выбора пути.
            overlay.hide()

        path = saver.default_path(self.settings)
        if self.settings.get("ask_where_to_save", True):
            fmt = self.settings.get("image_format", "png")
            chosen, _ = QFileDialog.getSaveFileName(
                None, tr("Save screenshot"), path,
                ";;".join([_FILTERS.get(fmt, _FILTERS["png"])]
                          + [v for k, v in _FILTERS.items() if k != fmt]))
            if not chosen:
                if overlay is not None:
                    overlay.show()
                    overlay.raise_()
                    overlay.activateWindow()
                return
            path = chosen

        if saver.save_pixmap(pixmap, path, self.settings):
            if self.settings.get("copy_after_save"):
                saver.copy_to_clipboard(pixmap)
            self._toast(tr("Saved"), os.path.basename(path), open_path=path)
        else:
            self._toast(tr("Save failed"), icon_name="info")
        self._finish_overlay()

    def _on_print(self, pixmap):
        overlay = self._overlay
        if overlay is not None:
            overlay.hide()
        saver.print_pixmap(pixmap)
        self._finish_overlay()

    def _finish_overlay(self):
        overlay, self._overlay = self._overlay, None
        if overlay is not None:
            overlay.closed.disconnect(self._on_overlay_closed)
            self._last_selection = self._selection_of(overlay)
            overlay.close()
        self._save_settings()

    @staticmethod
    def _selection_of(overlay):
        sel = overlay.selection.normalized()
        if sel.width() > 4 and sel.height() > 4:
            return QRect(sel).translated(overlay.geometry().topLeft())
        return None

    def _on_overlay_closed(self, rect):
        self._overlay = None
        if rect is not None:
            self._last_selection = rect
        # Цвет и толщина кисти живут между съёмками — оверлей пишет их в settings.
        self._save_settings()

    # ------------------------------------------------------------------ #
    #  Окна
    # ------------------------------------------------------------------ #
    def open_settings(self):
        if self._settings_win is not None:
            self._settings_win.close()
        win = SettingsWindow(self.settings, app=self)
        win.applied.connect(self.apply_settings)
        win.closed.connect(lambda: setattr(self, "_settings_win", None))
        self._settings_win = win
        win.center_on_cursor_screen()
        win.show()
        win.raise_()
        win.activateWindow()

    def open_about(self):
        if self._about_win is not None:
            self._about_win.close()
        win = AboutWindow()
        win.closed.connect(lambda: setattr(self, "_about_win", None))
        self._about_win = win
        win.center_on_cursor_screen()
        win.show()
        win.raise_()
        win.activateWindow()

    def open_updates(self):
        self.open_settings()
        if self._settings_win is not None:
            self._settings_win.tabs.set_index(3)

    # ------------------------------------------------------------------ #
    #  Настройки
    # ------------------------------------------------------------------ #
    def apply_settings(self, new_settings):
        old = dict(self.settings)
        self.settings.update(new_settings)
        config.save(self.settings)

        i18n.set_language(self.settings.get("language", "ru"))
        if self.settings.get("autostart") != old.get("autostart"):
            autostart.set_enabled(bool(self.settings.get("autostart")))
        self.hotkeys.apply(self.settings)
        if self.tray is not None:
            self.tray.retranslate()

    def reset_settings(self):
        """Сброс к заводским: удаляем конфиг и перезапускаемся. Перезапуск нужен
        не для красоты — язык, горячие клавиши и автозапуск проще поднять с нуля,
        чем переигрывать по одному."""
        self.hotkeys.stop()
        try:
            os.remove(CONFIG_PATH)
        except OSError:
            pass
        autostart.set_enabled(False)
        if updater.relaunch_app():
            # Помощник ждёт выхода процесса: уходим немедленно, иначе Qt успеет
            # записать настройки обратно на диск.
            os._exit(0)
        QTimer.singleShot(0, QApplication.instance().quit)

    def open_save_dir(self):
        folder = self.settings.get("save_dir") or os.path.expanduser("~")
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except OSError:
            pass

    def run_first_launch(self):
        """Первый запуск: программа свернулась в трей молча, и без подсказки её
        просто не находят."""
        if not IS_FIRST_RUN:
            return
        combo = pretty(self.settings.get("hotkey", ""))
        QTimer.singleShot(900, lambda: toast.show(
            tr("Shotly is running in the tray"),
            tr("Press %s to capture an area") % combo,
            icon_name="camera"))

    def sync_autostart(self):
        """Приводит реестр к настройке при запуске: пользователь мог убрать
        программу из автозапуска сторонним средством."""
        want = bool(self.settings.get("autostart"))
        if autostart.is_enabled() != want:
            autostart.set_enabled(want)

    def _save_settings(self):
        config.save(self.settings)

    # ------------------------------------------------------------------ #
    #  Обновления
    # ------------------------------------------------------------------ #
    def check_updates_async(self):
        if not self.settings.get("check_updates") or not updater.is_frozen():
            return
        threading.Thread(target=self._check_updates_worker, daemon=True).start()

    def _check_updates_worker(self):
        info = updater.check_update()
        if info.get("status") == "available":
            self.update_found.emit(info)

    def _on_update_found(self, info):
        self._toast("%s: %s" % (tr("Update available"), info.get("version", "")),
                    APP_NAME, icon_name="info", on_click=self.open_updates)

    # ------------------------------------------------------------------ #
    def _toast(self, text, subtext="", icon_name="check", open_path="",
               on_click=None):
        if not self.settings.get("notify", True) and on_click is None:
            return
        toast.show(text, subtext, icon_name, open_path, on_click)

    def quit(self):
        self.hotkeys.stop()
        self._save_settings()
        if self._overlay is not None:
            self._overlay.close()
        QTimer.singleShot(0, QApplication.instance().quit)
