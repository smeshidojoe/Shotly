"""
Выбор цвета и толщины линии — всплывающая панелька рядом с образцом цвета.

Тоже дочерний виджет оверлея: отдельное окно-попап отобрало бы у оверлея фокус,
и первый же клик мимо снял бы выделение.
"""

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QColorDialog, QWidget

from ..core.i18n import tr
from . import theme

# Палитра под скриншоты: яркие, читаемые на любом фоне.
SWATCHES = [
    "#ff2d2d", "#ff8a1f", "#ffd12e", "#38d16a", "#22c1c1", "#4f8cff",
    "#9b5cff", "#ff5cc0", "#ffffff", "#9aa3af", "#000000", "#7a4a1e",
]
WIDTHS = [2, 3, 5, 8]

_COLS = 6


class ColorPopup(QWidget):
    color_picked = Signal(str)
    width_picked = Signal(int)
    closed = Signal()

    def __init__(self, parent, color, width):
        super().__init__(parent)
        self._color = QColor(color)
        self._width = int(width)
        self._hover = (-1, -1)          # (секция, индекс): 0 цвета, 1 толщины, 2 «ещё»

        self._pad = theme.s(8)
        self._cell = theme.s(20)
        self._gap = theme.s(5)
        self._row_h = theme.s(24)
        self._font = QFont("Segoe UI")
        self._font.setPixelSize(theme.s(12))

        rows = (len(SWATCHES) + _COLS - 1) // _COLS
        w = self._pad * 2 + _COLS * self._cell + (_COLS - 1) * self._gap
        h = (self._pad * 2
             + rows * self._cell + (rows - 1) * self._gap
             + self._gap + self._row_h            # толщины
             + self._gap + self._row_h)           # «Другие цвета...»
        self.resize(w, h)
        self.setMouseTracking(True)

    # --- геометрия ------------------------------------------------------ #
    def _swatch_rect(self, i):
        row, col = divmod(i, _COLS)
        return QRect(self._pad + col * (self._cell + self._gap),
                     self._pad + row * (self._cell + self._gap),
                     self._cell, self._cell)

    def _widths_top(self):
        rows = (len(SWATCHES) + _COLS - 1) // _COLS
        return self._pad + rows * (self._cell + self._gap) + self._gap

    def _width_rect(self, i):
        n = len(WIDTHS)
        inner = self.width() - self._pad * 2
        cell = inner // n
        return QRect(self._pad + i * cell, self._widths_top(), cell, self._row_h)

    def _more_rect(self):
        top = self._widths_top() + self._row_h + self._gap
        return QRect(self._pad, top, self.width() - self._pad * 2, self._row_h)

    def _hit(self, pos):
        for i in range(len(SWATCHES)):
            if self._swatch_rect(i).contains(pos):
                return (0, i)
        for i in range(len(WIDTHS)):
            if self._width_rect(i).contains(pos):
                return (1, i)
        if self._more_rect().contains(pos):
            return (2, 0)
        return (-1, -1)

    # --- ввод ------------------------------------------------------------ #
    def mouseMoveEvent(self, e):
        hit = self._hit(e.position().toPoint())
        if hit != self._hover:
            self._hover = hit
            self.update()

    def leaveEvent(self, e):
        self._hover = (-1, -1)
        self.update()

    def mousePressEvent(self, e):
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        section, i = self._hit(e.position().toPoint())
        if section == 0:
            self._color = QColor(SWATCHES[i])
            self.color_picked.emit(SWATCHES[i])
            self.closed.emit()
        elif section == 1:
            self._width = WIDTHS[i]
            self.width_picked.emit(WIDTHS[i])
            self.update()
        elif section == 2:
            self._open_dialog()
        e.accept()

    def _open_dialog(self):
        dlg = QColorDialog(self._color, self)
        dlg.setOption(QColorDialog.DontUseNativeDialog, False)
        if dlg.exec() == QColorDialog.Accepted:
            col = dlg.selectedColor()
            if col.isValid():
                self._color = col
                self.color_picked.emit(col.name())
        self.closed.emit()

    # --- отрисовка -------------------------------------------------------- #
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = theme.color("panel")
        bg.setAlpha(246)
        p.setPen(QPen(theme.color("border"), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, theme.s(9), theme.s(9))

        for i, name in enumerate(SWATCHES):
            rect = QRectF(self._swatch_rect(i))
            p.setBrush(QColor(name))
            selected = QColor(name) == self._color
            if selected:
                p.setPen(QPen(QColor(theme.OVERLAY["active"]), theme.s(2)))
            elif self._hover == (0, i):
                p.setPen(QPen(theme.color("text"), 1))
            else:
                p.setPen(QPen(QColor(0, 0, 0, 90), 1))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                              theme.s(4), theme.s(4))

        # Толщина: точка размером с саму линию — понятнее числа.
        for i, w in enumerate(WIDTHS):
            rect = self._width_rect(i)
            if self._width == w:
                p.setPen(Qt.NoPen)
                p.setBrush(theme.color("field_hi"))
                p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1),
                                  theme.s(5), theme.s(5))
            elif self._hover == (1, i):
                p.setPen(Qt.NoPen)
                p.setBrush(theme.color("field"))
                p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1),
                                  theme.s(5), theme.s(5))
            p.setPen(Qt.NoPen)
            p.setBrush(self._color if self._color.alpha() else theme.color("text"))
            d = theme.s(w)
            p.drawEllipse(rect.center(), d / 2.0, d / 2.0)

        rect = self._more_rect()
        if self._hover == (2, 0):
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("field"))
            p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1),
                              theme.s(5), theme.s(5))
        p.setFont(self._font)
        p.setPen(QPen(theme.color("text_dim")))
        p.drawText(rect, Qt.AlignCenter, tr("More colors..."))
        p.end()

    def popup_at(self, top_right):
        """Ставит панельку левее точки top_right, не вылезая за окно-родителя."""
        parent = self.parentWidget()
        x = top_right.x() - self.width()
        y = top_right.y()
        if parent is not None:
            x = max(theme.s(4), min(x, parent.width() - self.width() - theme.s(4)))
            y = max(theme.s(4), min(y, parent.height() - self.height() - theme.s(4)))
        self.move(QPoint(int(x), int(y)))
        self.show()
        self.raise_()
