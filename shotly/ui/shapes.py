"""
Аннотации поверх снимка: карандаш, линия, стрелка, прямоугольник, маркер, текст
и размытие (рамкой и кистью).

Фигуры хранятся списком в координатах СНИМКА (не окна), поэтому их можно
отрисовать и на экране, и в итоговый файл одним и тем же кодом — вырезаемая
область просто сдвигает начало координат.

Размытие рисуется не краской, а вырезкой из заранее размытой копии снимка:
её отдаёт blur-провайдер (core/blur.BlurCache), который передают в draw().
"""

from math import hypot

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPolygonF)

TOOLS = ("pen", "line", "arrow", "rect", "marker", "eraser", "bucket",
         "quill", "text", "blur_rect", "blur_brush")

# «Ведро» и его напарник: заливка и снятие заливки.
BUCKET_MODES = ("fill", "unfill")

# Инструменты, которым цвет не нужен: у них своя панелька с видом и силой.
BLUR_TOOLS = ("blur_rect", "blur_brush")

# Формы, которые строятся по двум углам: и у контурной фигуры, и у размытия.
AREA_SHAPES = ("rect", "round", "ellipse")
BLUR_SHAPES = AREA_SHAPES

# Скругление углов: доля от меньшей стороны, но не больше предела — иначе
# небольшая область превращается в овал.
_ROUND_K = 0.22
_ROUND_MAX = 42.0

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
    def update_to(self, point, square=False, center=False):
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

    def draw(self, p, blur=None):
        p.setPen(self._pen())
        p.setBrush(Qt.NoBrush)
        p.drawLine(self.p1, self.p2)


class PenShape(Shape):
    kind = "pen"

    def __init__(self, color, width, start):
        super().__init__(color, width, start)
        self.points = [QPointF(start)]

    def update_to(self, point, square=False, center=False):
        # Точки ближе половины толщины линии на глаз не видны, а список растят.
        last = self.points[-1]
        if hypot(point.x() - last.x(), point.y() - last.y()) < 1.0:
            return
        self.points.append(QPointF(point))
        self.p2 = QPointF(point)

    def is_empty(self):
        return len(self.points) < 2

    def draw(self, p, blur=None):
        p.setPen(self._pen())
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(self.points))


def marker_width(width):
    """Толщина полосы маркера. Вынесена наружу: кружок под курсором должен
    показывать ту же ширину, какой ляжет мазок."""
    return max(6, int(width) * MARKER_WIDTH_K)


class MarkerShape(PenShape):
    kind = "marker"

    def _pen(self):
        col = QColor(self.color)
        col.setAlpha(MARKER_ALPHA)
        pen = QPen(col, marker_width(self.width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen


class LineShape(Shape):
    kind = "line"

    def update_to(self, point, square=False, center=False):
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

    def draw(self, p, blur=None):
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
    """Контурная фигура: прямоугольник, скруглённый прямоугольник или овал."""

    kind = "rect"

    def __init__(self, color, width, start, shape="rect"):
        super().__init__(color, width, start)
        self.shape = shape if shape in AREA_SHAPES else "rect"
        self.start = QPointF(start)     # точка нажатия: угол или центр

    def update_to(self, point, square=False, center=False):
        self.p1, self.p2 = corners(self.start, point, square, center)

    def rect(self):
        return QRectF(self.p1, self.p2).normalized()

    def path(self):
        return area_path(self.rect(), self.shape)

    def draw(self, p, blur=None):
        p.setPen(self._pen())
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.path())


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

    def draw(self, p, blur=None):
        if not self.text:
            return
        p.setPen(QPen(self.color))
        p.setFont(self.font())
        p.drawText(QRectF(self.p1.x(), self.p1.y(), 1e5, 1e5),
                   Qt.AlignLeft | Qt.AlignTop, self.text)


class _BlurShape(Shape):
    """Общее для размытий: параметры эффекта и заливка размытой копией снимка.

    Заливаем именно кистью-текстурой, а не обрезаем картинку по контуру:
    отсечение в Qt всегда жёсткое, и у овала с лассо края выходили бы
    лесенкой. Текстурная кисть рисуется со сглаживанием.
    """

    def __init__(self, color, width, start, blur_kind="pixel", blur_level=2):
        super().__init__(color, width, start)
        self.blur_kind = blur_kind
        self.blur_level = int(blur_level)

    def path(self):
        raise NotImplementedError

    def draw(self, p, blur=None):
        source = blur.get(self.blur_kind, self.blur_level) if blur else None
        if source is None or self.is_empty():
            return
        path = self.path()
        if path is None or path.isEmpty():
            return
        p.save()
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(Qt.NoPen)
            # Начало текстуры — начало координат снимка, поэтому размытая копия
            # ложится ровно поверх оригинала, без сдвига.
            p.setBrushOrigin(0, 0)
            p.setBrush(QBrush(source))
            p.drawPath(path)
        finally:
            p.restore()


class BlurAreaShape(_BlurShape):
    """Размытие областью: прямоугольник, скруглённый прямоугольник или овал."""

    kind = "blur_rect"

    def __init__(self, color, width, start, blur_kind="pixel", blur_level=2,
                 shape="rect"):
        super().__init__(color, width, start, blur_kind, blur_level)
        self.shape = shape if shape in BLUR_SHAPES else "rect"
        self.start = QPointF(start)     # точка нажатия: угол или центр

    def update_to(self, point, square=False, center=False):
        self.p1, self.p2 = corners(self.start, point, square, center)

    def is_empty(self):
        return self.rect().isEmpty()

    def rect(self):
        return QRectF(self.p1, self.p2).normalized()

    def path(self):
        return area_path(self.rect(), self.shape)


class BlurBrushShape(_BlurShape):
    """Размытие кистью: мазок открывает размытую копию снимка под собой."""

    kind = "blur_brush"

    def __init__(self, color, width, start, blur_kind="pixel", blur_level=2,
                 shape="rect"):
        super().__init__(color, width, start, blur_kind, blur_level)
        self.points = [QPointF(start)]

    def update_to(self, point, square=False, center=False):
        last = self.points[-1]
        if hypot(point.x() - last.x(), point.y() - last.y()) < 1.0:
            return
        self.points.append(QPointF(point))
        self.p2 = QPointF(point)

    def is_empty(self):
        # Одиночный тычок кистью — законный мазок: он закрашивает пятно шириной
        # с кисть. Требовать вторую точку, как у карандаша, тут неправильно.
        return not self.points

    def path(self):
        if len(self.points) == 1:
            # Из пути в одну точку stroker ничего не построит — рисуем пятно.
            path = QPainterPath()
            path.addEllipse(self.points[0], self.width / 2.0, self.width / 2.0)
            return path
        line = QPainterPath(self.points[0])
        for point in self.points[1:]:
            line.lineTo(point)
        stroker = QPainterPathStroker()
        stroker.setWidth(self.width)
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        return stroker.createStroke(line)


class ImageShape:
    """Вставленная картинка: живёт в списке фигур, но до фиксации её можно
    двигать и растягивать за ручки (см. Overlay._image_*)."""

    kind = "image"

    def __init__(self, pixmap, rect):
        self.pixmap = pixmap
        self.rect = QRectF(rect)

    def aspect(self):
        if self.pixmap.isNull() or self.pixmap.height() == 0:
            return 1.0
        return self.pixmap.width() / float(self.pixmap.height())

    def is_empty(self):
        return self.pixmap.isNull() or self.rect.width() < 2 or self.rect.height() < 2

    def draw(self, p, blur=None):
        if self.pixmap.isNull():
            return
        p.save()
        try:
            # Сглаживание при масштабировании: вставленную картинку почти всегда
            # ужимают, и без него она рассыпается на лесенки.
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(self.rect, self.pixmap, QRectF(self.pixmap.rect()))
        finally:
            p.restore()


class PathShape(Shape):
    """Перо: узлы и кривые между ними — работает как в Figma.

    Узел хранит точку и две ручки: входящую и исходящую, каждая вектором от
    самой точки. Клик ставит узел с нулевыми ручками (прямой отрезок), клик с
    протяжкой растягивает симметричную пару (гладкая кривая), а протяжка с Alt
    ломает симметрию — так делают углы, где кривая входит и выходит по-разному.
    """

    kind = "quill"

    def __init__(self, color, width, start):
        super().__init__(color, width, start)
        self.nodes = [self._node(start)]
        self.closed = False
        self.preview = None          # куда тянется незакреплённый отрезок

    @staticmethod
    def _node(point):
        return [QPointF(point), QPointF(0, 0), QPointF(0, 0)]

    # --- построение ---------------------------------------------------- #
    def add_node(self, point):
        self.nodes.append(self._node(point))

    def drag_handle(self, point, symmetric=True):
        """Тянем ручку последнего узла прямо во время клика."""
        node = self.nodes[-1]
        out = QPointF(point.x() - node[0].x(), point.y() - node[0].y())
        node[2] = out
        if symmetric:
            node[1] = QPointF(-out.x(), -out.y())

    def drop_node(self):
        """Backspace убирает последний поставленный узел."""
        if len(self.nodes) > 1:
            self.nodes.pop()
            return True
        return False

    def first_point(self):
        return self.nodes[0][0]

    def last_point(self):
        return self.nodes[-1][0]

    def is_empty(self):
        return len(self.nodes) < 2 and not self.closed

    def close_path(self):
        self.closed = True
        self.preview = None

    # --- геометрия ------------------------------------------------------ #
    @staticmethod
    def _segment(path, a, b):
        """Кубический сегмент: из первого узла выходит его исходящая ручка, во
        второй входит его же входящая."""
        c1 = QPointF(a[0].x() + a[2].x(), a[0].y() + a[2].y())
        c2 = QPointF(b[0].x() + b[1].x(), b[0].y() + b[1].y())
        path.cubicTo(c1, c2, b[0])

    def path(self):
        path = QPainterPath(self.nodes[0][0])
        for i in range(1, len(self.nodes)):
            self._segment(path, self.nodes[i - 1], self.nodes[i])
        if self.closed and len(self.nodes) > 1:
            self._segment(path, self.nodes[-1], self.nodes[0])
            path.closeSubpath()
        elif self.preview is not None:
            self._segment(path, self.nodes[-1], self._node(self.preview))
        return path

    def draw(self, p, blur=None):
        p.setPen(self._pen())
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.path())


class FillShape:
    """Залитая область: готовая цветная маска и её место в кадре.

    Маску считает core/fill по самому изображению, поэтому заливка ложится
    ровно внутрь контура, даже если его рисовали от руки. Храним результат
    целиком — так её можно снять «антизаливкой», не перебирая историю.
    """

    kind = "fill"

    def __init__(self, pixmap, rect, color):
        self.pixmap = pixmap
        self.rect = QRectF(rect)
        self.color = QColor(color)

    def is_empty(self):
        return self.pixmap.isNull()

    def contains(self, point):
        """Попала ли точка в саму краску, а не просто в её прямоугольник."""
        if not self.rect.contains(point):
            return False
        image = self.pixmap.toImage()
        x = int((point.x() - self.rect.left()) * image.width() / self.rect.width())
        y = int((point.y() - self.rect.top()) * image.height() / self.rect.height())
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            return False
        return image.pixelColor(x, y).alpha() > 40

    def draw(self, p, blur=None):
        if not self.pixmap.isNull():
            p.drawPixmap(self.rect.topLeft(), self.pixmap)


class EraserShape(PenShape):
    """Ластик: стирает всё нарисованное до него — и штрихи, и размытие.

    Работает только потому, что аннотации живут отдельным прозрачным слоем:
    мазок вычищает в нём пиксели (CompositionMode_Clear), а сам снимок под
    слоем остаётся нетронутым. Стирать «половину фигуры» иначе было бы нечем —
    фигуры векторные и целиком.
    """

    kind = "eraser"

    def is_empty(self):
        return not self.points

    def path(self):
        if len(self.points) == 1:
            path = QPainterPath()
            path.addEllipse(self.points[0], self.width / 2.0, self.width / 2.0)
            return path
        line = QPainterPath(self.points[0])
        for point in self.points[1:]:
            line.lineTo(point)
        stroker = QPainterPathStroker()
        stroker.setWidth(self.width)
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        return stroker.createStroke(line)

    def tail_path(self):
        """Только последний отрезок мазка.

        Во время стирания слой правят по кусочку: перерисовывать весь экран на
        каждое движение мыши — это десятки миллисекунд на кадр и заметные
        рывки."""
        if len(self.points) < 2:
            return self.path()
        line = QPainterPath(self.points[-2])
        line.lineTo(self.points[-1])
        stroker = QPainterPathStroker()
        stroker.setWidth(self.width)
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        return stroker.createStroke(line)

    def erase(self, p, path=None):
        """Вычищает путь из слоя аннотаций."""
        p.save()
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.black)          # цвет не важен: режим стирает пиксели
            p.drawPath(self.path() if path is None else path)
        finally:
            p.restore()

    def draw(self, p, blur=None):
        self.erase(p)


def eraser_width(width):
    """Ластик заметно шире линии — им затирают, а не рисуют."""
    return max(14, int(width) * 7)


def tool_width_key(tool):
    """Какой настройкой меряется толщина инструмента."""
    if tool == "eraser":
        return "eraser_width"
    if tool == "blur_brush":
        return "blur_brush"
    return "draw_width"


def blur_brush_width(width):
    """Кисть размытия заметно шире линии: замазывать ей приходится надписи и
    лица, а не рисовать штрихи."""
    return max(12, int(width) * 6)


def area_path(rect, shape):
    """Контур фигуры по прямоугольнику: сама рамка, скруглённая рамка или овал."""
    path = QPainterPath()
    if shape == "ellipse":
        path.addEllipse(rect)
    elif shape == "round":
        radius = min(_ROUND_MAX, min(rect.width(), rect.height()) * _ROUND_K)
        path.addRoundedRect(rect, radius, radius)
    else:
        path.addRect(rect)
    return path


def shape_handles(shape):
    """Точки, за которые фигуру правят поштучно: [(идентификатор, точка)].

    Идентификатор — пара (индекс, роль): роль 0 у самого узла, 1 и 2 у входящей
    и исходящей ручки пера. Один список на все фигуры позволяет и оверлею, и
    отрисовке не знать, что именно редактируют.
    """
    if isinstance(shape, PathShape):
        handles = []
        for index, node in enumerate(shape.nodes):
            handles.append(((index, 0), QPointF(node[0])))
            for role in (1, 2):
                vector = node[role]
                if vector.x() or vector.y():
                    handles.append(((index, role),
                                    QPointF(node[0].x() + vector.x(),
                                            node[0].y() + vector.y())))
        return handles

    points = getattr(shape, "points", None)
    if points:
        # У длинных мазков карандаша точек сотни — показывать каждую бессмысленно,
        # берём с прореживанием.
        step = max(1, len(points) // 40)
        return [((index, 0), QPointF(points[index]))
                for index in range(0, len(points), step)]

    if isinstance(shape, (LineShape, ArrowShape)) or type(shape) is Shape:
        return [((0, 0), QPointF(shape.p1)), ((1, 0), QPointF(shape.p2))]
    return []


def move_handle(shape, handle_id, point, symmetric=True):
    """Двигает одну точку фигуры. symmetric касается только ручек пера."""
    index, role = handle_id
    if isinstance(shape, PathShape):
        if index >= len(shape.nodes):
            return
        node = shape.nodes[index]
        if role == 0:
            # Узел едет вместе со своими ручками — они заданы вектором от него.
            node[0] = QPointF(point)
            return
        vector = QPointF(point.x() - node[0].x(), point.y() - node[0].y())
        node[role] = vector
        if symmetric:
            other = 1 if role == 2 else 2
            node[other] = QPointF(-vector.x(), -vector.y())
        return

    points = getattr(shape, "points", None)
    if points and index < len(points):
        points[index] = QPointF(point)
        return

    if index == 0:
        shape.p1 = QPointF(point)
    else:
        shape.p2 = QPointF(point)


def shape_bounds(shape):
    """Прямоугольник, в котором фигура помещается целиком.

    Единая мерка для инструмента выбора: рамку с ручками надо показать вокруг
    чего угодно — от стрелки до вставленной картинки."""
    rect = getattr(shape, "rect", None)
    if isinstance(rect, QRectF):
        return QRectF(rect)
    if callable(rect):
        return QRectF(rect())
    if hasattr(shape, "path"):
        area = shape.path().boundingRect()
    elif getattr(shape, "points", None):
        area = QPainterPath(shape.points[0])
        for point in shape.points[1:]:
            area.lineTo(point)
        area = area.boundingRect()
    elif hasattr(shape, "bounds"):
        area = shape.bounds()
    else:
        area = QRectF(shape.p1, shape.p2).normalized()
    # Толстая линия выходит за геометрию пути на половину пера.
    pad = getattr(shape, "width", 0) / 2.0 + 2.0
    return area.adjusted(-pad, -pad, pad, pad)


def transform_shape(shape, transform):
    """Двигает и масштабирует фигуру. Точки у всех разные, поэтому проходим по
    известным полям: две опорные точки, список точек, узлы пера, прямоугольник."""
    for name in ("p1", "p2", "start"):
        point = getattr(shape, name, None)
        if isinstance(point, QPointF):
            setattr(shape, name, transform.map(point))

    points = getattr(shape, "points", None)
    if points:
        shape.points = [transform.map(point) for point in points]

    nodes = getattr(shape, "nodes", None)
    if nodes:
        # Ручку двигаем как вектор: её начало уже переехало вместе с узлом.
        origin = transform.map(QPointF(0, 0))
        for node in nodes:
            node[0] = transform.map(node[0])
            for index in (1, 2):
                moved = transform.map(node[index])
                node[index] = QPointF(moved.x() - origin.x(),
                                      moved.y() - origin.y())

    rect = getattr(shape, "rect", None)
    if isinstance(rect, QRectF):
        shape.rect = transform.mapRect(rect)


def move_shape(shape, dx, dy):
    from PySide6.QtGui import QTransform
    transform_shape(shape, QTransform().translate(dx, dy))


def scale_shape(shape, source, target):
    """Вписывает фигуру из прямоугольника source в target."""
    from PySide6.QtGui import QTransform
    if source.width() <= 0 or source.height() <= 0:
        return
    kx = target.width() / source.width()
    ky = target.height() / source.height()
    transform = (QTransform()
                 .translate(target.left(), target.top())
                 .scale(kx, ky)
                 .translate(-source.left(), -source.top()))
    transform_shape(shape, transform)
    if hasattr(shape, "width") and not isinstance(shape, FillShape):
        # Толщина линии тоже должна расти вместе с фигурой, иначе увеличенная
        # стрелка выглядит нарисованной другим инструментом.
        shape.width = max(1, int(round(shape.width * (kx + ky) / 2.0)))


def hit_shape(shape, point, slack=6.0):
    """Попал ли клик в фигуру. Для контуров считаем попаданием и близость к
    линии: попасть мышью в двухпиксельный штрих иначе невозможно."""
    if isinstance(shape, (ImageShape, FillShape)):
        if isinstance(shape, FillShape):
            return shape.contains(point)
        return shape.rect.contains(point)

    reach = max(slack, getattr(shape, "width", 2) / 2.0 + slack)
    if isinstance(shape, (BlurAreaShape, RectShape, PathShape, BlurBrushShape,
                          EraserShape)):
        path = shape.path()
        if path.contains(point):
            return True
        stroker = QPainterPathStroker()
        stroker.setWidth(reach * 2)
        return stroker.createStroke(path).contains(point)

    if getattr(shape, "points", None):
        for index in range(1, len(shape.points)):
            if _near_segment(point, shape.points[index - 1],
                             shape.points[index], reach):
                return True
        return len(shape.points) == 1 and _near_segment(
            point, shape.points[0], shape.points[0], reach)

    if isinstance(shape, TextShape):
        return shape.bounds().adjusted(-4, -4, 4, 4).contains(point)
    return _near_segment(point, shape.p1, shape.p2, reach)


def _near_segment(point, a, b, reach):
    """Расстояние от точки до отрезка меньше reach."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = dx * dx + dy * dy
    if length <= 0.000001:
        return hypot(point.x() - a.x(), point.y() - a.y()) <= reach
    t = ((point.x() - a.x()) * dx + (point.y() - a.y()) * dy) / length
    t = max(0.0, min(1.0, t))
    return hypot(point.x() - (a.x() + dx * t),
                 point.y() - (a.y() + dy * t)) <= reach


def corners(start, point, square=False, center=False):
    """Два угла фигуры по точке нажатия и текущей позиции мыши.

    Shift (square) уравнивает стороны, Alt (center) превращает точку нажатия в
    центр: фигура растёт во все стороны сразу. Вместе — круг или квадрат из
    центра, как в графических редакторах.
    """
    dx = point.x() - start.x()
    dy = point.y() - start.y()
    if square:
        side = min(abs(dx), abs(dy))
        dx = side if dx >= 0 else -side
        dy = side if dy >= 0 else -side
    if center:
        return (QPointF(start.x() - dx, start.y() - dy),
                QPointF(start.x() + dx, start.y() + dy))
    return QPointF(start), QPointF(start.x() + dx, start.y() + dy)


def text_size_for(width):
    return int(10 + int(width) * 3)


_BY_KIND = {
    "pen": PenShape, "marker": MarkerShape, "line": LineShape,
    "arrow": ArrowShape, "rect": RectShape, "text": TextShape,
    "eraser": EraserShape, "quill": PathShape,
    "blur_rect": BlurAreaShape, "blur_brush": BlurBrushShape,
}


def create(kind, color, width, start, blur_kind="pixel", blur_level=2,
           blur_shape="rect", draw_shape="rect"):
    cls = _BY_KIND.get(kind, LineShape)
    if kind in BLUR_TOOLS:
        if kind == "blur_brush":
            width = blur_brush_width(width)
        return cls(color, width, start, blur_kind, blur_level, blur_shape)
    if kind == "rect":
        return cls(color, width, start, draw_shape)
    if kind == "eraser":
        return cls(color, eraser_width(width), start)
    return cls(color, width, start)


def draw_all(painter, shapes, clip=None, blur=None):
    """Рисует список фигур. clip (в координатах снимка) нужен только при сборке
    результата: на экране фигуры не обрезаются, а в файл идёт лишь выделение.
    blur — источник размытых копий снимка для фигур размытия."""
    painter.save()
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        if clip is not None:
            painter.setClipRect(clip)
        for sh in shapes:
            sh.draw(painter, blur)
    finally:
        painter.restore()
