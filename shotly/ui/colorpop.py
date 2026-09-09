"""
Выбор цвета и толщины линии — всплывающая панелька рядом с образцом цвета.
Форму фигуры выбирают не здесь, а прямо у её кнопки (ui/flyout.py).

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

# Секции панельки: цвета, толщина, системный выбор цвета.
_COLOR, _WIDTH, _MORE = range(3)


class ColorPopup(QWidget):
    color_picked = Signal(str)
    width_picked = Signal(int)
    closed = Signal()

    def __init__(self, parent, color, width):
        super().__init__(parent)
        self._color = QColor(color)
        self._width = int(width)
        self._hover = (-1, -1)          # (секция, индекс)

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
             + (self._gap + self._row_h) * 2)   # толщина и «другие цвета»
        self.resize(w, h)
        self.setMouseTracking(True)

    # --- геометрия ------------------------------------------------------ #
    def _swatch_rect(self, i):
        row, col = divmod(i, _COLS)
        return QRect(self._pad + col * (self._cell + self._gap),
                     self._pad + row * (self._cell + self._gap),
                     self._cell, self._cell)

    def _row_top(self, index):
        """Верх ряда под палитрой: 0 — толщина, 1 — «другие цвета»."""
        rows = (len(SWATCHES) + _COLS - 1) // _COLS
        return (self._pad + rows * (self._cell + self._gap)
                + self._gap + (self._row_h + self._gap) * index)

    def _cells(self, index, count):
        inner = self.width() - self._pad * 2
        cell = inner // count
        top = self._row_top(index)
        return [QRect(self._pad + i * cell, top, cell, self._row_h)
                for i in range(count)]

    def _more_rect(self):
        return QRect(self._pad, self._row_top(1),
                     self.width() - self._pad * 2, self._row_h)

    def _hit(self, pos):
        for i in range(len(SWATCHES)):
            if self._swatch_rect(i).contains(pos):
                return (_COLOR, i)
        for i, rect in enumerate(self._cells(0, len(WIDTHS))):
            if rect.contains(pos):
                return (_WIDTH, i)
        if self._more_rect().contains(pos):
            return (_MORE, 0)
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
        if section == _COLOR:
            self._color = QColor(SWATCHES[i])
            self.color_picked.emit(SWATCHES[i])
            self.closed.emit()
        elif section == _WIDTH:
            self._width = WIDTHS[i]
            self.width_picked.emit(WIDTHS[i])
            self.update()
        elif section == _MORE:
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

        self._paint_swatches(p)
        self._paint_widths(p)

        rect = self._more_rect()
        if self._hover == (_MORE, 0):
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("field"))
            p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1),
                              theme.s(5), theme.s(5))
        p.setFont(self._font)
        p.setPen(QPen(theme.color("text_dim")))
        p.drawText(rect, Qt.AlignCenter, tr("More colors..."))
        p.end()

    def _cell_bg(self, p, rect, selected, hovered):
        if not selected and not hovered:
            return
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("field_hi") if selected else theme.color("field"))
        p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1),
                          theme.s(5), theme.s(5))

    def _paint_swatches(self, p):
        for i, name in enumerate(SWATCHES):
            rect = QRectF(self._swatch_rect(i))
            p.setBrush(QColor(name))
            selected = QColor(name) == self._color
            if selected:
                p.setPen(QPen(QColor(theme.OVERLAY["active"]), theme.s(2)))
            elif self._hover == (_COLOR, i):
                p.setPen(QPen(theme.color("text"), 1))
            else:
                p.setPen(QPen(QColor(0, 0, 0, 90), 1))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                              theme.s(4), theme.s(4))

    def _paint_widths(self, p):
        # Толщина: точка размером с саму линию — понятнее числа.
        for i, (rect, w) in enumerate(zip(self._cells(0, len(WIDTHS)), WIDTHS)):
            self._cell_bg(p, rect, w == self._width, self._hover == (_WIDTH, i))
            p.setPen(Qt.NoPen)
            p.setBrush(self._color if self._color.alpha() else theme.color("text"))
            d = theme.s(w)
            p.drawEllipse(rect.center(), d / 2.0, d / 2.0)

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
