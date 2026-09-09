"""
Выезжающий ряд вариантов рядом с кнопкой инструмента.

Форму фигуры выбирают там же, где сам инструмент: клик по уже выбранной кнопке
выдвигает сбоку остальные формы. Прятать это в палитре цветов было неудобно —
связь между рядом иконок и кнопкой инструмента ниоткуда не читалась.
"""

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRect,
                            QRectF, Qt, Signal)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import icons, theme


class Flyout(QWidget):
    """Столбик вариантов: [(значение, имя иконки), ...].

    Вертикальный, как и сама панель инструментов: горизонтальная полоска рядом
    с вертикальным доком выглядела чужеродно и заезжала на кадр.
    """

    picked = Signal(str)
    closed = Signal()

    def __init__(self, parent, items, current):
        super().__init__(parent)
        self._items = list(items)
        self._current = current
        self._hover = -1

        self._pad = theme.s(4)
        self._cell = theme.s(28)
        self._gap = theme.s(2)
        self._icon = theme.s(18)

        count = len(self._items)
        self.resize(self._pad * 2 + self._cell,
                    self._pad * 2 + self._cell * count + self._gap * (count - 1))
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)
        self._anim = QPropertyAnimation(self, b"geometry", self)

    def set_current(self, value):
        """Подсветить другой вариант — например, когда его выбрали колесом."""
        if value != self._current:
            self._current = value
            self.update()

    # --- геометрия ------------------------------------------------------ #
    def _cell_rect(self, i):
        return QRect(self._pad, self._pad + i * (self._cell + self._gap),
                     self._cell, self._cell)

    def _hit(self, pos):
        for i in range(len(self._items)):
            if self._cell_rect(i).contains(pos):
                return i
        return -1

    # --- ввод ------------------------------------------------------------ #
    def mouseMoveEvent(self, e):
        hit = self._hit(e.position().toPoint())
        if hit != self._hover:
            self._hover = hit
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        i = self._hit(e.position().toPoint())
        if i >= 0:
            self._current = self._items[i][0]
            self.picked.emit(self._current)
        self.closed.emit()
        e.accept()

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

        for i, (value, icon_name) in enumerate(self._items):
            rect = self._cell_rect(i)
            selected = value == self._current
            if selected or i == self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.OVERLAY["active"]) if selected
                           else theme.color("field_hi"))
                p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1),
                                  theme.s(6), theme.s(6))
            col = (theme.OVERLAY["on_active"] if selected
                   else theme.PALETTE["text"])
            p.drawPixmap(rect.center().x() - self._icon // 2 + 1,
                         rect.center().y() - self._icon // 2 + 1,
                         icons.pixmap(icon_name, self._icon, col))
        p.end()

    # --- показ ------------------------------------------------------------ #
    def slide_from(self, anchor):
        """Выезжает из-под кнопки anchor (её прямоугольник в координатах
        родителя): вправо, если там есть место, иначе влево."""
        parent = self.parentWidget()
        gap = theme.s(6)
        top = anchor.center().y() - self.height() // 2
        if parent is not None:
            top = max(0, min(top, parent.height() - self.height()))

        right_x = anchor.right() + gap
        if parent is not None and right_x + self.width() > parent.width():
            left_x = anchor.left() - gap - self.width()
            target = QRect(max(0, left_x), top, self.width(), self.height())
            start_x = anchor.left() - gap
        else:
            target = QRect(right_x, top, self.width(), self.height())
            start_x = anchor.right() + gap

        # Полоска именно выезжает из кнопки: появление «из ниоткуда» не
        # показывает, к чему эти варианты относятся.
        self.setGeometry(QRect(start_x, target.y(), 1, target.height()))
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setDuration(140)
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()
