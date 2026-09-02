"""
Аннотации поверх снимка: карандаш, линия, стрелка, прямоугольник, маркер, текст.

Фигуры хранятся списком в координатах СНИМКА (не окна), поэтому их можно
отрисовать и на экране, и в итоговый файл одним и тем же кодом — вырезаемая
область просто сдвигает начало координат.
"""

from math import hypot

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF

TOOLS = ("pen", "line", "arrow", "rect", "marker", "text")

# Маркер: полупрозрачный и заведомо толстый — иначе он не отличался бы от
# карандаша того же цвета.
MARKER_ALPHA = 90
MARKER_WIDTH_K = 4


class Shape:
    """Базовая фигура: цвет, толщина, две опорные точки."""

    kind = "line"

    def __init__(self, color, width, start):
        self.color = QColor(color)
        self.width = int(width)
        self.p1 = QPointF(start)
        self.p2 = QPointF(start)

    # --- построение мышью --------------------------------------------- #
    def update_to(self, point, square=False):
        self.p2 = QPointF(point)

    def is_empty(self):
        """Фигура-точка: пользователь кликнул и не потянул — рисовать нечего."""
        return (abs(self.p2.x() - self.p1.x()) < 2
                and abs(self.p2.y() - self.p1.y()) < 2)

    # --- отрисовка ------------------------------------------------------ #
    def _pen(self):
        pen = QPen(self.color, self.width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def draw(self, p):
        p.setPen(self._pen())
        p.setBrush(Qt.NoBrush)
        p.drawLine(self.p1, self.p2)


class PenShape(Shape):
    kind = "pen"

    def __init__(self, color, width, start):
        super().__init__(color, width, start)
        self.points = [QPointF(start)]

    def update_to(self, point, square=False):
        # Точки ближе половины толщины линии на глаз не видны, а список растят.
        last = self.points[-1]
        if hypot(point.x() - last.x(), point.y() - last.y()) < 1.0:
            return
        self.points.append(QPointF(point))
        self.p2 = QPointF(point)

    def is_empty(self):
        return len(self.points) < 2

    def draw(self, p):
        p.setPen(self._pen())
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(self.points))


class MarkerShape(PenShape):
    kind = "marker"

    def _pen(self):
        col = QColor(self.color)
        col.setAlpha(MARKER_ALPHA)
        pen = QPen(col, max(6, self.width * MARKER_WIDTH_K))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen


class LineShape(Shape):
    kind = "line"

    def update_to(self, point, square=False):
        # Shift — прижать линию к 0/45/90 градусам.
        if square:
            dx, dy = point.x() - self.p1.x(), point.y() - self.p1.y()
            if abs(dx) > abs(dy) * 2:
                point = QPointF(point.x(), self.p1.y())
            elif abs(dy) > abs(dx) * 2:
                point = QPointF(self.p1.x(), point.y())
            else:
                d = min(abs(dx), abs(dy))
                point = QPointF(self.p1.x() + d * (1 if dx > 0 else -1),
                                self.p1.y() + d * (1 if dy > 0 else -1))
        self.p2 = QPointF(point)


class ArrowShape(LineShape):
    kind = "arrow"

    # Наконечник: длина и половина ширины в толщинах линии. Раньше он строился
    # от угла раствора, и на коротких стрелках выходил широким лопухом.
    HEAD_LEN = 3.6
    HEAD_HALF_W = 1.5

    def draw(self, p):
        length = hypot(self.p2.x() - self.p1.x(), self.p2.y() - self.p1.y())
        if length < 0.5:
            return

        head = min(max(10.0, self.width * self.HEAD_LEN), length)
        half = max(4.0, self.width * self.HEAD_HALF_W)
        ux = (self.p2.x() - self.p1.x()) / length      # единичный вектор к острию
        uy = (self.p2.y() - self.p1.y()) / length
        base = QPointF(self.p2.x() - ux * head, self.p2.y() - uy * head)

        # Линию ведём до основания наконечника, а не до острия: иначе толстая
        # линия торчит из треугольника и кончик выглядит тупым.
        pen = self._pen()
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawLine(self.p1, base)

        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawPolygon(QPolygonF([
            QPointF(self.p2),
            QPointF(base.x() - uy * half, base.y() + ux * half),
            QPointF(base.x() + uy * half, base.y() - ux * half),
        ]))


class RectShape(Shape):
    kind = "rect"

    def update_to(self, point, square=False):
        if square:
            dx, dy = point.x() - self.p1.x(), point.y() - self.p1.y()
            d = min(abs(dx), abs(dy))
            point = QPointF(self.p1.x() + d * (1 if dx > 0 else -1),
                            self.p1.y() + d * (1 if dy > 0 else -1))
        self.p2 = QPointF(point)

    def rect(self):
        return QRectF(self.p1, self.p2).normalized()

    def draw(self, p):
        p.setPen(self._pen())
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect())


class TextShape(Shape):
    kind = "text"

    def __init__(self, color, width, start, text="", point_size=None):
        super().__init__(color, width, start)
        self.text = text
        # Размер шрифта привязан к толщине линии: один ползунок управляет всем
        # рисованием, отдельный «размер текста» был бы лишней настройкой.
        self.point_size = point_size or text_size_for(width)

    def is_empty(self):
        return not self.text.strip()

    def font(self):
        f = QFont("Segoe UI")
        f.setPixelSize(self.point_size)
        f.setBold(True)
        return f

    def bounds(self):
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(self.font())
        return fm.boundingRect(QRectF(self.p1.x(), self.p1.y(), 1e5, 1e5),
                               Qt.AlignLeft | Qt.AlignTop, self.text)

    def draw(self, p):
        if not self.text:
            return
        p.setPen(QPen(self.color))
        p.setFont(self.font())
        p.drawText(QRectF(self.p1.x(), self.p1.y(), 1e5, 1e5),
                   Qt.AlignLeft | Qt.AlignTop, self.text)


def text_size_for(width):
    return int(10 + int(width) * 3)


_BY_KIND = {
    "pen": PenShape, "marker": MarkerShape, "line": LineShape,
    "arrow": ArrowShape, "rect": RectShape, "text": TextShape,
}


def create(kind, color, width, start):
    return _BY_KIND.get(kind, LineShape)(color, width, start)


def draw_all(painter, shapes, clip=None):
    """Рисует список фигур. clip (в координатах снимка) нужен только при сборке
    результата: на экране фигуры не обрезаются, а в файл идёт лишь выделение."""
    painter.save()
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        if clip is not None:
            painter.setClipRect(clip)
        for sh in shapes:
            sh.draw(painter)
    finally:
        painter.restore()
