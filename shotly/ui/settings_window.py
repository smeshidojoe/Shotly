"""
Окно настроек: Основные / Горячие клавиши / Форматы / Обновления.

Правки идут в КОПИЮ настроек и уезжают наружу только по «ОК» — «Отмена» должна
уметь вернуть всё как было, включая уже переназначенные горячие клавиши.
"""

import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QStackedWidget, QVBoxLayout, QWidget)

from ..core import config, saver, updater
from ..core.constants import APP_NAME, APP_VERSION
from ..core.i18n import tr
from . import theme
from .widgets import HotkeyEdit, TabBar, Window


class _Checker(QObject):
    """Проверка обновлений в фоне: сеть не должна морозить окно."""

    done = Signal(dict)

    def run(self):
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        self.done.emit(updater.check_update())


class _Downloader(QObject):
    progress = Signal(float)
    done = Signal(bool, str)

    def __init__(self, url):
        super().__init__()
        self._url = url

    def run(self):
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            updater.download_update(self._url, self.progress.emit)
            self.done.emit(True, "")
        except Exception as exc:
            self.done.emit(False, str(exc))


class SettingsWindow(Window):
    applied = Signal(dict)
    # Язык меняется прямо в открытом окне: владелец переключает i18n и зовёт
    # retranslate(). Пересоздавать окно нельзя — оно мигало бы на глазах.
    language_changed = Signal(str)

    def __init__(self, settings, app=None, parent=None):
        super().__init__(tr("Settings"), parent)
        self.s = dict(settings)          # рабочая копия
        self._app = app                  # для действий над самой программой
        self._update_info = None
        self._checker = None
        self._downloader = None
        # [(виджет, английский ключ)] — что переписать при смене языка.
        self._labels = []

        self.setFixedWidth(theme.s(520))

        root = QVBoxLayout(self)
        root.setContentsMargins(theme.s(16), self.title_h + theme.s(12),
                                theme.s(16), theme.s(14))
        root.setSpacing(theme.s(12))

        self._tab_keys = ["General", "Hotkeys", "Formats", "Updates"]
        self.tabs = TabBar([tr(k) for k in self._tab_keys], self)
        root.addWidget(self.tabs)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._page_general())
        self.stack.addWidget(self._page_hotkeys())
        self.stack.addWidget(self._page_formats())
        self.stack.addWidget(self._page_updates())
        self.tabs.changed.connect(self.stack.setCurrentIndex)
        root.addWidget(self.stack)

        root.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = self._t(QPushButton(self), "OK")
        ok.setProperty("accent", True)
        ok.clicked.connect(self._accept)
        cancel = self._t(QPushButton(self), "Cancel")
        cancel.clicked.connect(self.close)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        root.addLayout(buttons)

        # Страницы разной высоты дёргали бы окно при переключении вкладок.
        self.stack.setCurrentIndex(0)
        self.adjustSize()
        self.setFixedHeight(max(self.sizeHint().height(), theme.s(340)))

    # ------------------------------------------------------------------ #
    #  Вспомогательное
    # ------------------------------------------------------------------ #
    def _t(self, widget, key):
        """Ставит подпись и запоминает виджет: при смене языка перепишем её."""
        widget.setText(tr(key))
        self._labels.append((widget, key))
        return widget

    def _check(self, key, label_key, page_layout):
        box = self._t(QCheckBox(self), label_key)
        box.setChecked(bool(self.s.get(key)))
        box.toggled.connect(lambda on, k=key: self.s.__setitem__(k, bool(on)))
        page_layout.addWidget(box)
        return box

    def retranslate(self):
        """Перевод открытого окна: заголовок, вкладки и все запомненные подписи.
        Динамические строки (пример имени, качество JPEG) пересчитываются, а
        статус обновления сбрасывается — переводить чужой текст ошибки нечем."""
        self.set_title(tr("Settings"))
        self.tabs.set_titles([tr(k) for k in self._tab_keys])
        for widget, key in self._labels:
            widget.setText(tr(key))
        self._sync_version_label()
        self._on_quality(self._q_slider.value())
        self._on_template(self._tpl.text())
        self._disarm_reset()
        self._update_status.setText("")
        self._hotkey_warn.setText("")

    @staticmethod
    def _row(*widgets, stretch_last=True):
        row = QHBoxLayout()
        row.setSpacing(theme.s(8))
        for i, w in enumerate(widgets):
            if isinstance(w, int):
                row.addSpacing(w)
            elif isinstance(w, str):
                row.addStretch(1)
            else:
                row.addWidget(w, 1 if (stretch_last and i == len(widgets) - 1) else 0)
        return row

    @staticmethod
    def _page():
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.s(10))
        return page, lay

    # ------------------------------------------------------------------ #
    #  Вкладки
    # ------------------------------------------------------------------ #
    def _page_general(self):
        page, lay = self._page()
        self._check("autostart", "Launch at Windows startup", lay)
        self._check("notify", "Show notifications about copying and saving", lay)
        self._check("remember_selection", "Remember selection position", lay)
        self._check("capture_cursor", "Capture mouse cursor", lay)
        self._check("copy_after_save", "Copy to clipboard after saving", lay)

        lay.addSpacing(theme.s(6))
        lay.addWidget(self._t(QLabel(self), "Save folder"))
        self._dir_edit = QLineEdit(self.s.get("save_dir", ""), self)
        self._dir_edit.textChanged.connect(
            lambda t: self.s.__setitem__("save_dir", t))
        browse = self._t(QPushButton(self), "Browse...")
        browse.clicked.connect(self._pick_dir)
        lay.addLayout(self._row(self._dir_edit, browse, stretch_last=False))

        lay.addSpacing(theme.s(2))
        lay.addWidget(self._t(QLabel(self), "Language"))
        combo = QComboBox(self)
        combo.addItem("Русский", "ru")
        combo.addItem("English", "en")
        combo.setCurrentIndex(0 if self.s.get("language") == "ru" else 1)
        combo.currentIndexChanged.connect(self._on_language)
        self._lang = combo
        lay.addWidget(combo)

        lay.addStretch(1)
        tools = QHBoxLayout()
        open_dir = self._t(QPushButton(self), "Open screenshots folder")
        open_dir.clicked.connect(self._open_dir)
        self._reset_btn = self._t(QPushButton(self), "Reset settings")
        self._reset_btn.clicked.connect(self._on_reset)
        # Сброс — необратимое действие, поэтому двухступенчатый: первый клик
        # взводит кнопку, второй выполняет. Отдельного окна с вопросом ради
        # этого заводить не стали.
        self._reset_armed = False
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._disarm_reset)
        tools.addWidget(open_dir)
        tools.addWidget(self._reset_btn)
        tools.addStretch(1)
        lay.addLayout(tools)
        return page

    def _on_language(self, index):
        lang = self._lang.itemData(index)
        if lang == self.s.get("language"):
            return
        self.s["language"] = lang
        self.language_changed.emit(lang)

    def _open_dir(self):
        if self._app is not None:
            self._app.settings["save_dir"] = self.s.get("save_dir", "")
            self._app.open_save_dir()

    def _on_reset(self):
        if not self._reset_armed:
            self._reset_armed = True
            self._reset_btn.setText(tr("Click again to confirm"))
            self._reset_btn.setStyleSheet("color: %s;" % theme.PALETTE["danger"])
            self._reset_timer.start(4000)
            return
        self._disarm_reset()
        if self._app is not None:
            self._app.reset_settings()

    def _disarm_reset(self):
        self._reset_armed = False
        self._reset_btn.setText(tr("Reset settings"))
        self._reset_btn.setStyleSheet("")

    def _page_hotkeys(self):
        page, lay = self._page()
        self._hotkey_rows = []
        for key_flag, key_combo, title in (
                ("hotkey_enabled", "hotkey", "Main hotkey"),
                ("hotkey_fullsave_on", "hotkey_fullsave",
                 "Quick save of the whole screen"),
                ("hotkey_fullcopy_on", "hotkey_fullcopy",
                 "Quick copy of the whole screen")):
            box = self._t(QCheckBox(self), title)
            box.setChecked(bool(self.s.get(key_flag)))
            edit = HotkeyEdit(self.s.get(key_combo, ""), self)
            edit.setFixedWidth(theme.s(190))
            edit.setEnabled(box.isChecked())
            box.toggled.connect(lambda on, k=key_flag, w=edit: (
                self.s.__setitem__(k, bool(on)), w.setEnabled(bool(on))))
            edit.combo_changed.connect(
                lambda combo, k=key_combo: self._set_combo(k, combo))
            row = QHBoxLayout()
            row.addWidget(box, 1)
            row.addWidget(edit, 0)
            lay.addLayout(row)
            self._hotkey_rows.append((key_combo, edit))

        self._hotkey_warn = QLabel("", self)
        self._hotkey_warn.setStyleSheet("color: %s;" % theme.PALETTE["danger"])
        lay.addWidget(self._hotkey_warn)
        lay.addStretch(1)
        return page

    def _set_combo(self, key, combo):
        """Одно сочетание на две функции — вторая молча не работала бы."""
        for other_key, edit in self._hotkey_rows:
            if other_key != key and edit.combo() == combo:
                self._hotkey_warn.setText(tr("This combination is already used"))
                for k, w in self._hotkey_rows:
                    if k == key:
                        w.set_combo(self.s.get(key, ""))
                return
        self._hotkey_warn.setText("")
        self.s[key] = combo

    def _page_formats(self):
        page, lay = self._page()

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(self._t(QLabel(self), "Image format"))
        self._fmt = QComboBox(self)
        for name, value in (("PNG", "png"), ("JPG", "jpg"), ("BMP", "bmp")):
            self._fmt.addItem(name, value)
        self._fmt.setCurrentIndex(
            max(0, self._fmt.findData(self.s.get("image_format", "png"))))
        self._fmt.currentIndexChanged.connect(self._on_format)
        fmt_row.addStretch(1)
        fmt_row.addWidget(self._fmt)
        lay.addLayout(fmt_row)

        q_row = QHBoxLayout()
        self._q_label = QLabel("%s: %d" % (tr("JPEG quality"),
                                           self.s.get("jpeg_quality", 92)), self)
        self._q_slider = QSlider(Qt.Horizontal, self)
        self._q_slider.setRange(10, 100)
        self._q_slider.setValue(int(self.s.get("jpeg_quality", 92)))
        self._q_slider.valueChanged.connect(self._on_quality)
        q_row.addWidget(self._q_label)
        q_row.addWidget(self._q_slider, 1)
        lay.addLayout(q_row)
        self._sync_quality_enabled()

        lay.addWidget(self._t(QLabel(self), "File name template"))
        self._tpl = QLineEdit(self.s.get("filename_template", ""), self)
        self._tpl.textChanged.connect(self._on_template)
        lay.addWidget(self._tpl)
        self._tpl_example = QLabel("", self)
        self._tpl_example.setProperty("dim", True)
        lay.addWidget(self._tpl_example)
        hint = self._t(QLabel(self), "%n — the first free number in the folder")
        hint.setProperty("dim", True)
        lay.addWidget(hint)
        self._on_template(self._tpl.text())

        self._check("ask_where_to_save", "Ask where to save every time", lay)
        lay.addStretch(1)
        return page

    def _pick_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, tr("Choose save folder"), self._dir_edit.text() or
            os.path.expanduser("~"))
        if path:
            self._dir_edit.setText(path)

    def _on_format(self, index):
        self.s["image_format"] = self._fmt.itemData(index)
        self._sync_quality_enabled()
        self._on_template(self._tpl.text())

    def _sync_quality_enabled(self):
        on = self.s.get("image_format") == "jpg"
        self._q_slider.setEnabled(on)
        self._q_label.setEnabled(on)

    def _on_quality(self, value):
        self.s["jpeg_quality"] = int(value)
        self._q_label.setText("%s: %d" % (tr("JPEG quality"), value))

    def _on_template(self, text):
        self.s["filename_template"] = text
        probe = dict(self.s)
        probe["filename_template"] = text
        name = saver.build_name(probe, time.time(),
                                folder=self.s.get("save_dir", ""))
        ext = {"png": "png", "jpg": "jpg", "bmp": "bmp"}.get(
            self.s.get("image_format", "png"), "png")
        self._tpl_example.setText("%s: %s.%s" % (tr("Example"), name, ext))

    def _page_updates(self):
        page, lay = self._page()
        self._check("check_updates", "Notify about new versions", lay)

        lay.addSpacing(theme.s(4))
        self._version_label = QLabel(self)
        self._sync_version_label()
        lay.addWidget(self._version_label)

        row = QHBoxLayout()
        self._check_btn = self._t(QPushButton(self), "Check now")
        self._check_btn.clicked.connect(self._do_check)
        self._update_btn = self._t(QPushButton(self), "Install and restart")
        self._update_btn.setProperty("accent", True)
        self._update_btn.clicked.connect(self._do_update)
        self._update_btn.hide()
        row.addWidget(self._check_btn)
        row.addWidget(self._update_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self._update_status = QLabel("", self)
        self._update_status.setProperty("dim", True)
        self._update_status.setWordWrap(True)
        lay.addWidget(self._update_status)
        lay.addStretch(1)
        return page

    def _sync_version_label(self):
        self._version_label.setText("%s: %s %s" % (tr("Current version"),
                                                   APP_NAME, APP_VERSION))

    # --- обновления ------------------------------------------------------ #
    def begin_update(self, info):
        """Запуск установки с уже известным релизом — так окно открывается из
        уведомления о новой версии и сразу качает, не проверяя повторно."""
        self.tabs.set_index(3)
        self._update_info = info
        self._update_btn.setVisible(bool(info.get("download_url")))
        self._update_status.setText("%s: %s" % (tr("Update available"),
                                                info.get("version", "")))
        self._do_update()

    def _do_check(self):
        self._check_btn.setEnabled(False)
        self._update_status.setText(tr("Checking..."))
        self._checker = _Checker()
        self._checker.done.connect(self._on_check_done)
        self._checker.run()

    def _on_check_done(self, info):
        self._check_btn.setEnabled(True)
        status = info.get("status")
        if status == "available":
            self._update_info = info
            self._update_status.setText("%s: %s" % (tr("Update available"),
                                                    info.get("version", "")))
            # Без zip-ассета ставить нечего — кнопку не показываем.
            self._update_btn.setVisible(bool(info.get("download_url")))
        elif status == "current":
            self._update_status.setText(tr("You have the latest version"))
        else:
            self._update_status.setText("%s: %s" % (tr("Check failed"),
                                                    info.get("error", "")))

    def _do_update(self):
        if not self._update_info:
            return
        if not updater.is_frozen():
            # Из исходников подменять нечего: exe нет.
            self._update_status.setText(tr("Update failed"))
            return
        self._update_btn.setEnabled(False)
        self._update_status.setText(tr("Downloading..."))
        self._downloader = _Downloader(self._update_info.get("download_url"))
        self._downloader.progress.connect(
            lambda f: self._update_status.setText("%s %d%%" % (tr("Downloading..."),
                                                               int(f * 100))))
        self._downloader.done.connect(self._on_download_done)
        self._downloader.run()

    def _on_download_done(self, ok, error):
        if not ok:
            self._update_btn.setEnabled(True)
            self._update_status.setText("%s: %s" % (tr("Update failed"), error))
            return
        if updater.restart_to_update():
            # Помощник ждёт, пока освободится exe. Настройки сохраняем через
            # владельца и выходим штатно — жёсткий os._exit оставлял за собой
            # ругань Qt на недоубитые потоки.
            self.applied.emit(self.s)
            if self._app is not None:
                self._app.quit_for_update()
            else:
                QApplication.instance().quit()
            return
        self._update_btn.setEnabled(True)
        self._update_status.setText(tr("Update failed"))

    # ------------------------------------------------------------------ #
    def _accept(self):
        self.applied.emit(config.validate(dict(self.s)))
        self.close()
