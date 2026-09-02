"""
Тост-уведомление в углу экрана.

Своё окно, а не QSystemTrayIcon.showMessage: системный баннер выглядит чужеродно,
живёт по правилам центра уведомлений Windows (может быть отключён «Не беспокоить»)
и не умеет открывать папку по клику.
"""

import os
import subprocess

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRect,
                            QRectF, Qt, QTimer)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import icons, theme

_LIFETIME_MS = 2600
_FADE_MS = 160
_live = []          # держим ссылки: без них тост соберёт сборщик мусора


class Toast(QWidget):
    def __init__(self, text, subtext="", icon_name="check", open_path="",
                 on_click=None, sticky=False, on_dismiss=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._text = text
        self._subtext = subtext
        self._icon = icon_name
        self._open_path = open_path
        self._on_click = on_click
        # Липкий тост не гаснет сам: сообщение об обновлении должно дождаться
        # пользователя, а не мигнуть, пока он смотрит в другое окно.
        self._sticky = bool(sticky)
        self._on_dismiss = on_dismiss
        self._dismissed = False
        self._hover = False
        self.setMouseTracking(True)

        self._font = QFont("Segoe UI")
        self._font.setPixelSize(theme.s(13))
        self._sub_font = QFont("Segoe UI")
        self._sub_font.setPixelSize(theme.s(11))

        self._pad = theme.s(12)
        self._icon_side = theme.s(18)
        self._gap = theme.s(10)
        self._radius = theme.s(10)

        fm, sfm = QFontMetrics(self._font), QFontMetrics(self._sub_font)
        text_w = fm.horizontalAdvance(text)
        if subtext:
            # Длинный путь не должен растягивать тост на пол-экрана.
            self._subtext = sfm.elidedText(subtext, Qt.ElideMiddle, theme.s(280))
            text_w = max(text_w, sfm.horizontalAdvance(self._subtext))
        h = self._pad * 2 + fm.height() + (sfm.height() + theme.s(2) if subtext else 0)
        w = self._pad * 2 + self._icon_side + self._gap + text_w
        self._close_side = theme.s(14)
        if self._sticky:
            w += self._gap + self._close_side      # место под крестик
        self.resize(int(w), int(h))

        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    # ------------------------------------------------------------------ #
    def show_at_corner(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or \
                 QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        margin = theme.s(16)
        self.move(QPoint(area.right() - self.width() - margin,
                         area.bottom() - self.height() - margin))
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setDuration(_FADE_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()
        if not self._sticky:
            self._timer.start(_LIFETIME_MS)
        _live.append(self)
        return self

    def dismiss(self):
        self._anim.stop()
        self._anim.setDuration(_FADE_MS)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.close)
        self._anim.start()

    def closeEvent(self, e):
        if self in _live:
            _live.remove(self)
        super().closeEvent(e)

    # ------------------------------------------------------------------ #
    def enterEvent(self, e):
        self._hover = True
        self._timer.stop()               # не убегает из-под курсора
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        if not self._sticky:
            self._timer.start(_LIFETIME_MS // 2)
        self.update()

    def _close_rect(self):
        return QRect(self.width() - self._pad - self._close_side,
                     int((self.height() - self._close_side) / 2),
                     self._close_side, self._close_side)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._sticky and self._close_rect().contains(e.position().toPoint()):
            # Крестик — это «больше не напоминать», а не «потом»: вызывающий
            # решает, что с этим делать (мы запоминаем версию обновления).
            self._dismissed = True
            if self._on_dismiss is not None:
                self._on_dismiss()
            self.dismiss()
            return
        if self._on_click is not None:
            self._on_click()
        elif self._open_path:
            _reveal(self._open_path)
        self.dismiss()

    # ------------------------------------------------------------------ #
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = theme.color("panel")
        bg.setAlpha(250)
        p.setPen(QPen(theme.color("accent" if self._hover else "border"), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, self._radius, self._radius)

        pm = icons.pixmap(self._icon, self._icon_side, theme.PALETTE["accent"])
        p.drawPixmap(self._pad, int((self.height() - self._icon_side) / 2), pm)

        right_pad = self._pad
        if self._sticky:
            cr = self._close_rect()
            p.drawPixmap(cr.topLeft(), icons.pixmap(
                "close", self._close_side, theme.PALETTE["text_dim"]))
            right_pad += self._close_side + self._gap

        x = self._pad + self._icon_side + self._gap
        fm = QFontMetrics(self._font)
        if self._subtext:
            sfm = QFontMetrics(self._sub_font)
            total = fm.height() + theme.s(2) + sfm.height()
            y = (self.height() - total) / 2
            p.setFont(self._font)
            p.setPen(QPen(theme.color("text")))
            p.drawText(QRectF(x, y, self.width() - x - right_pad, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, self._text)
            p.setFont(self._sub_font)
            p.setPen(QPen(theme.color("text_dim")))
            p.drawText(QRectF(x, y + fm.height() + theme.s(2),
                              self.width() - x - right_pad, sfm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, self._subtext)
        else:
            p.setFont(self._font)
            p.setPen(QPen(theme.color("text")))
            p.drawText(QRectF(x, 0, self.width() - x - right_pad, self.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, self._text)
        p.end()


def _reveal(path):
    """Открыть проводник с выделенным файлом (или просто папку)."""
    try:
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif os.path.isdir(path):
            os.startfile(path)
    except Exception:
        pass


def show(text, subtext="", icon_name="check", open_path="", on_click=None,
         sticky=False, on_dismiss=None):
    return Toast(text, subtext, icon_name, open_path, on_click,
                 sticky, on_dismiss).show_at_corner()
