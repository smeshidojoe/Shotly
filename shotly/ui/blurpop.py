"""
Панелька настроек размытия: вид (пиксели или мягкое), сила и размер кисти.

Открывается с той же кнопки панели, что и палитра цветов: у инструментов
размытия цвета нет, зато есть свои три параметра. Как и палитра — дочерний
виджет оверлея, а не отдельное окно: попап отобрал бы у оверлея фокус.
"""

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core.blur import LEVELS
from ..core.i18n import tr
from . import icons, theme

BRUSH_WIDTHS = (2, 4, 7, 11)      # множится на 6 в shapes.blur_brush_width

_KINDS = (("pixel", "mosaic", "Pixels"), ("soft", "droplet", "Blur"))


class BlurPopup(QWidget):
    kind_picked = Signal(str)
    level_picked = Signal(int)
    brush_picked = Signal(int)
    closed = Signal()

    def __init__(self, parent, kind, level, brush):
        super().__init__(parent)
        self._kind = kind
        self._level = int(level)
        self._brush = int(brush)
        self._hover = (-1, -1)          # (секция, индекс)

        self._pad = theme.s(8)
        self._gap = theme.s(6)
        self._kind_h = theme.s(34)
        self._row_h = theme.s(26)
        self._label_h = theme.s(16)

        self._font = QFont("Segoe UI")
        self._font.setPixelSize(theme.s(12))
        self._small = QFont("Segoe UI")
        self._small.setPixelSize(theme.s(11))

        width = theme.s(212)
        height = (self._pad * 2 + self._kind_h + self._gap
                  + (self._label_h + self._row_h + self._gap) * 2 - self._gap)
        self.resize(width, height)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

    # --- геометрия ------------------------------------------------------ #
    def _kind_rect(self, i):
        inner = self.width() - self._pad * 2
        cell = (inner - self._gap) // 2
        return QRect(self._pad + i * (cell + self._gap), self._pad,
                     cell, self._kind_h)

    def _levels_top(self):
        return self._pad + self._kind_h + self._gap + self._label_h

    def _level_rect(self, i):
        inner = self.width() - self._pad * 2
        cell = inner // len(LEVELS)
        return QRect(self._pad + i * cell, self._levels_top(), cell, self._row_h)

    def _brushes_top(self):
        return self._levels_top() + self._row_h + self._gap + self._label_h

    def _brush_rect(self, i):
        inner = self.width() - self._pad * 2
        cell = inner // len(BRUSH_WIDTHS)
        return QRect(self._pad + i * cell, self._brushes_top(), cell, self._row_h)

    def _hit(self, pos):
        for i in range(len(_KINDS)):
            if self._kind_rect(i).contains(pos):
                return (0, i)
        for i in range(len(LEVELS)):
            if self._level_rect(i).contains(pos):
                return (1, i)
        for i in range(len(BRUSH_WIDTHS)):
            if self._brush_rect(i).contains(pos):
                return (2, i)
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
            self._kind = _KINDS[i][0]
            self.kind_picked.emit(self._kind)
        elif section == 1:
            self._level = LEVELS[i]
            self.level_picked.emit(self._level)
        elif section == 2:
            self._brush = BRUSH_WIDTHS[i]
            self.brush_picked.emit(self._brush)
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
        self._paint_label(p, tr("Strength"),
                          self._levels_top() - self._label_h)
        self._paint_levels(p)
        self._paint_label(p, tr("Brush size"),
                          self._brushes_top() - self._label_h)
        self._paint_brushes(p)
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
            self._cell_bg(p, rect, selected, self._hover == (0, i))
            col = (theme.OVERLAY["active"] if selected
                   else theme.PALETTE["text_dim"])
            p.drawPixmap(rect.left() + theme.s(10),
                         rect.top() + (rect.height() - side) // 2,
                         icons.pixmap(icon_name, side, col))
            p.setPen(QPen(QColor(col)))
            p.drawText(QRect(rect.left() + theme.s(10) + side + theme.s(8),
                             rect.top(), rect.width(), rect.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, tr(label))

    def _paint_label(self, p, text, top):
        p.setFont(self._small)
        p.setPen(QPen(theme.color("text_dim")))
        p.drawText(QRect(self._pad, top, self.width() - self._pad * 2,
                         self._label_h),
                   Qt.AlignLeft | Qt.AlignVCenter, text)

    def _paint_levels(self, p):
        # Сила показана размером клеток: чем крупнее, тем сильнее замазывает.
        for i, level in enumerate(LEVELS):
            rect = self._level_rect(i)
            self._cell_bg(p, rect, level == self._level, self._hover == (1, i))
            cell = theme.s(2 + level)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("text" if level == self._level else "text_dim"))
            block = QRectF(rect.center().x() - cell, rect.center().y() - cell,
                           cell * 2, cell * 2)
            p.drawRect(block)

    def _paint_brushes(self, p):
        for i, width in enumerate(BRUSH_WIDTHS):
            rect = self._brush_rect(i)
            self._cell_bg(p, rect, width == self._brush, self._hover == (2, i))
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("text" if width == self._brush else "text_dim"))
            d = theme.s(width)
            p.drawEllipse(rect.center(), d / 2.0, d / 2.0)

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
