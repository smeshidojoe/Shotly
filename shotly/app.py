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
from .core import windows as win_utils
from .core.constants import CONFIG_PATH
from .core.hotkey import HotkeyManager
from .core.i18n import tr
from .ui import theme, toast
from .ui.about import AboutWindow
from .ui.overlay import Overlay
from .ui.settings_window import SettingsWindow

# Как часто спрашиваем GitHub о новой версии в фоне.
_UPDATE_INTERVAL_MS = 2 * 60 * 60 * 1000

_FILTERS = {
    "png": "PNG (*.png)",
    "jpg": "JPEG (*.jpg *.jpeg)",
    "bmp": "BMP (*.bmp)",
}


class App(QObject):
    update_found = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        had_config = os.path.isfile(CONFIG_PATH)
        self.settings = config.load()
        i18n.set_language(self.settings.get("language", "ru"))
        if not had_config:
            # Первый запуск: автозапуск мог прописать установщик галочкой в
            # мастере. Принимаем реестр за исходное состояние — иначе
            # sync_autostart тут же стёр бы то, что пользователь выбрал.
            self.settings["autostart"] = autostart.is_enabled()
        # Пишем сразу на старте: при первом запуске файл появляется до того, как
        # пользователь что-то поменял, а после обновления программы в него
        # дописываются ключи, которых в старой версии не было.
        config.save(self.settings)

        self.tray = None
        self._resetting = False           # идёт сброс: конфиг писать больше нельзя
        self._overlay = None
        self._settings_win = None
        self._about_win = None
        self._last_selection = None       # QRect в координатах экрана
        self._update_timer = None
        self._pending_update = None

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

        rect = capture.virtual_rect()
        # Список окон снимаем здесь, пока оверлея ещё нет: он сам станет верхним
        # окном и закрыл бы собой всё остальное.
        wins = (win_utils.list_windows(rect)
                if self.settings.get("highlight_windows", True) else ())
        overlay = Overlay(shot, rect.topLeft(), self.settings, wins)
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
        self._settings_win = self._build_settings(self.settings)
        self._settings_win.center_on_cursor_screen()
        self._show(self._settings_win)

    def _build_settings(self, draft):
        win = SettingsWindow(draft, app=self)
        win.applied.connect(self.apply_settings)
        win.language_changed.connect(self._relanguage_settings)
        win.closed.connect(self._forget_settings_win)
        return win

    def _forget_settings_win(self):
        # Пересборка окна закрывает старое: ссылку чистим только если она ещё
        # указывает на закрывшееся окно, иначе затрём только что созданное.
        sender = self.sender()
        if sender is self._settings_win:
            self._settings_win = None

    def _relanguage_settings(self, lang):
        """Смена языка прямо в открытом окне: переключаем словарь и просим окно
        переписать подписи. Пересоздание окна выглядело бы как мигание —
        настройки исчезали и появлялись бы на каждом переключении."""
        i18n.set_language(lang)
        if self.tray is not None:
            self.tray.retranslate()
        if self._settings_win is not None:
            self._settings_win.retranslate()

    @staticmethod
    def _show(win):
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
        self._show(win)

    def open_updates(self):
        self.open_settings()
        if self._settings_win is not None:
            self._settings_win.tabs.set_index(3)

    # ------------------------------------------------------------------ #
    #  Настройки
    # ------------------------------------------------------------------ #
    def apply_settings(self, new_settings):
        self.settings.update(new_settings)
        config.save(self.settings)

        i18n.set_language(self.settings.get("language", "ru"))
        # Пишем реестр всегда, а не только при смене галочки: так чинится
        # рассинхрон, если запись удалили или испортили снаружи.
        autostart.set_enabled(bool(self.settings.get("autostart")))
        self.hotkeys.apply(self.settings)
        if self.tray is not None:
            self.tray.retranslate()

    def reset_settings(self):
        """Сброс к заводским: удаляем конфиг и перезапускаемся. Перезапуск нужен
        не для красоты — язык, горячие клавиши и автозапуск проще поднять с нуля,
        чем переигрывать по одному."""
        # Флаг ставим ДО удаления файла: любое сохранение после этого момента
        # (закрытие оверлея, выход) воскресило бы конфиг со старыми значениями.
        self._resetting = True
        try:
            os.remove(CONFIG_PATH)
        except OSError:
            pass
        autostart.set_enabled(False)
        updater.relaunch_app()
        self._shutdown(save=False)

    def open_save_dir(self):
        folder = self.settings.get("save_dir") or os.path.expanduser("~")
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except OSError:
            pass

    def sync_autostart(self):
        """Настройка — источник истины: на старте приводим реестр к галочке.

        Выключено — запись удаляется (чинит «застрявший» автозапуск от прошлой
        установки); включено — значение перезаписывается актуальным путём к exe,
        иначе после переустановки в другую папку автозапуск указывал бы в
        пустоту."""
        autostart.set_enabled(bool(self.settings.get("autostart")))

    def _save_settings(self):
        if self._resetting:
            return
        config.save(self.settings)

    # ------------------------------------------------------------------ #
    #  Обновления
    # ------------------------------------------------------------------ #
    def start_update_watch(self):
        """Тихая проверка новых версий: первая через ~8 c после старта, дальше
        раз в 2 часа. Только для собранного exe — из исходников подменять нечего.
        Нагрузка ничтожна: один HTTP-запрос к GitHub в фоновом потоке."""
        if not updater.is_frozen():
            return
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(_UPDATE_INTERVAL_MS)
        self._update_timer.timeout.connect(self._check_updates_bg)
        self._update_timer.start()
        QTimer.singleShot(8000, self._check_updates_bg)

    def _check_updates_bg(self):
        if not self.settings.get("check_updates", True):
            return
        threading.Thread(target=self._check_updates_worker, daemon=True).start()

    def _check_updates_worker(self):
        info = updater.check_update()
        if info.get("status") == "available":
            self.update_found.emit(info)

    def _on_update_found(self, info):
        if not self.settings.get("check_updates", True):
            return
        version = info.get("version") or ""
        if not info.get("download_url"):
            return                    # без zip-ассета ставить всё равно нечего
        if version and version == self.settings.get("update_dismissed_version"):
            return                    # об этой версии уже сказали, и её закрыли
        self._pending_update = info
        toast.show("%s: %s" % (tr("Update available"), version),
                   tr("Click to install"), icon_name="info",
                   on_click=self._install_pending_update,
                   sticky=True, on_dismiss=self._dismiss_pending_update)

    def _install_pending_update(self):
        info, self._pending_update = self._pending_update, None
        if not info:
            return
        self.open_settings()
        if self._settings_win is not None:
            self._settings_win.begin_update(info)

    def _dismiss_pending_update(self):
        info, self._pending_update = self._pending_update, None
        version = (info or {}).get("version") or ""
        if version:
            self.settings["update_dismissed_version"] = version
            self._save_settings()

    # ------------------------------------------------------------------ #
    def _toast(self, text, subtext="", icon_name="check", open_path="",
               on_click=None):
        if not self.settings.get("notify", True):
            return
        toast.show(text, subtext, icon_name, open_path, on_click)

    def quit(self):
        self._shutdown()

    def quit_for_update(self):
        """Выход перед подменой exe: помощник уже запущен и ждёт, когда файл
        освободится."""
        self._shutdown()

    def _shutdown(self, save=True):
        """Штатное завершение. Раньше здесь был os._exit — он убивал процесс, не
        дожидаясь потоков, и Qt на выходе ругался «QThreadStorage: entry
        destroyed before end of thread». Теперь сначала снимаем горячие клавиши
        и закрываем окна, потом даём циклу событий закончиться самому."""
        self.hotkeys.stop()
        if self._update_timer is not None:
            self._update_timer.stop()
        if save:
            self._save_settings()
        overlay, self._overlay = self._overlay, None
        if overlay is not None:
            overlay.close()
        for win in (self._settings_win, self._about_win):
            if win is not None:
                win.close()
        QTimer.singleShot(0, QApplication.instance().quit)
