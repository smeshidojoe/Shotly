"""
Панелька настроек размытия: вид (пиксели или мягкое) и сила.

Форму области выбирают у самой кнопки инструмента (ui/flyout.py), а размер
кисти меняют на лету — Alt и правая кнопка мыши.

Открывается своей кнопкой в группе размытия — у этих инструментов нет цвета,
зато есть четыре собственных параметра. Как и палитра цветов, это дочерний
виджет оверлея, а не отдельное окно: попап отобрал бы у оверлея фокус.
"""

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core.blur import LEVELS
from ..core.i18n import tr
from . import icons, theme

_KINDS = (("pixel", "mosaic", "Pixels"), ("soft", "droplet", "Blur"))

# Секции панельки: вид и сила.
_KIND, _LEVEL = range(2)


class BlurPopup(QWidget):
    kind_picked = Signal(str)
    level_picked = Signal(int)
    closed = Signal()

    def __init__(self, parent, kind, level):
        super().__init__(parent)
        self._kind = kind
        self._level = int(level)
        self._hover = (-1, -1)          # (секция, индекс)

        self._pad = theme.s(8)
        self._gap = theme.s(6)
        self._kind_h = theme.s(34)
        self._row_h = theme.s(28)
        self._label_h = theme.s(16)

        self._font = QFont("Segoe UI")
        self._font.setPixelSize(theme.s(12))
        self._small = QFont("Segoe UI")
        self._small.setPixelSize(theme.s(11))

        width = theme.s(212)
        rows = 1                        # только сила, со своей подписью
        height = (self._pad * 2 + self._kind_h
                  + (self._gap + self._label_h + self._row_h) * rows)
        self.resize(width, height)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

    # --- геометрия ------------------------------------------------------ #
    def _row_top(self, index):
        """Верх ряда с ячейками: сейчас он один — сила."""
        return (self._pad + self._kind_h
                + (self._gap + self._label_h + self._row_h) * index
                + self._gap + self._label_h)

    def _cells(self, index, count):
        inner = self.width() - self._pad * 2
        cell = inner // count
        top = self._row_top(index)
        return [QRect(self._pad + i * cell, top, cell, self._row_h)
                for i in range(count)]

    def _kind_rect(self, i):
        inner = self.width() - self._pad * 2
        cell = (inner - self._gap) // 2
        return QRect(self._pad + i * (cell + self._gap), self._pad,
                     cell, self._kind_h)

    def _hit(self, pos):
        for i in range(len(_KINDS)):
            if self._kind_rect(i).contains(pos):
                return (_KIND, i)
        for i, rect in enumerate(self._cells(0, len(LEVELS))):
            if rect.contains(pos):
                return (_LEVEL, i)
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
        if section == _KIND:
            self._kind = _KINDS[i][0]
            self.kind_picked.emit(self._kind)
        elif section == _LEVEL:
            self._level = LEVELS[i]
            self.level_picked.emit(self._level)
        # Панель не закрываем: параметры обычно подбирают в несколько кликов.
        self.update()
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

        self._paint_kinds(p)
        self._paint_label(p, tr("Strength"), 0)
        self._paint_levels(p)
        p.end()

    def _cell_bg(self, p, rect, selected, hovered):
        if not selected and not hovered:
            return
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("field_hi") if selected else theme.color("field"))
        p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1),
                          theme.s(6), theme.s(6))

    def _paint_kinds(self, p):
        side = theme.s(16)
        p.setFont(self._font)
        for i, (key, icon_name, label) in enumerate(_KINDS):
            rect = self._kind_rect(i)
            selected = key == self._kind
            self._cell_bg(p, rect, selected, self._hover == (_KIND, i))
            col = (theme.OVERLAY["active"] if selected
                   else theme.PALETTE["text_dim"])
            p.drawPixmap(rect.left() + theme.s(10),
                         rect.top() + (rect.height() - side) // 2,
                         icons.pixmap(icon_name, side, col))
            p.setPen(QPen(QColor(col)))
            p.drawText(QRect(rect.left() + theme.s(10) + side + theme.s(8),
                             rect.top(), rect.width(), rect.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, tr(label))

    def _paint_label(self, p, text, row):
        p.setFont(self._small)
        p.setPen(QPen(theme.color("text_dim")))
        top = self._row_top(row) - self._label_h
        p.drawText(QRect(self._pad, top, self.width() - self._pad * 2,
                         self._label_h),
                   Qt.AlignLeft | Qt.AlignVCenter, text)

    def _paint_levels(self, p):
        # Сила показана размером клеток: чем крупнее, тем сильнее замазывает.
        for i, (rect, level) in enumerate(zip(self._cells(0, len(LEVELS)),
                                              LEVELS)):
            self._cell_bg(p, rect, level == self._level,
                          self._hover == (_LEVEL, i))
            cell = theme.s(2 + level)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("text" if level == self._level else "text_dim"))
            p.drawRect(QRectF(rect.center().x() - cell, rect.center().y() - cell,
                              cell * 2, cell * 2))

    # --- показ ------------------------------------------------------------ #
    def popup_at(self, top_right):
        """Ставит панельку левее точки, не вылезая за окно-родителя."""
        parent = self.parentWidget()
        x = top_right.x() - self.width()
        y = top_right.y()
        if parent is not None:
            x = max(theme.s(4), min(x, parent.width() - self.width() - theme.s(4)))
            y = max(theme.s(4), min(y, parent.height() - self.height() - theme.s(4)))
        self.move(QPoint(int(x), int(y)))
        self.show()
        self.raise_()
