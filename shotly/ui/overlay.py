"""
Оверлей съёмки: затемнённый снимок рабочего стола, рамка выделения, панели
инструментов и рисование поверх выделенной области.

Одно окно на весь виртуальный рабочий стол (все мониторы сразу), поэтому
координаты внутри — это координаты снимка со сдвигом на левый верхний угол
виртуального экрана. Никакого DPI-масштабирования: приложение стартует с
QT_ENABLE_HIGHDPI_SCALING=0, логический пиксель равен физическому.
"""

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImageReader, QPainter,
                           QPen, QPixmap)
from PySide6.QtWidgets import QFileDialog, QLineEdit, QWidget

from ..core import capture
from ..core import windows as win_utils
from ..core import fill as fill_mod
from ..core.blur import BlurCache
from ..core.constants import DIM_ALPHA, HANDLE_SIZE
from ..core.i18n import tr
from . import shapes as shapes_mod
from . import theme
from .blurpop import BlurPopup
from .colorpop import ColorPopup
from .flyout import Flyout
from .history import History
from .toolbars import ActionPanel, ToolPanel

# Ручки рамки: имя -> (доля по X, доля по Y) и курсор.
_HANDLES = {
    "tl": (0.0, 0.0), "t": (0.5, 0.0), "tr": (1.0, 0.0),
    "r":  (1.0, 0.5), "br": (1.0, 1.0), "b": (0.5, 1.0),
    "bl": (0.0, 1.0), "l":  (0.0, 0.5),
}
_HANDLE_CURSORS = {
    "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
    "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
    "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
    "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
}

# Режимы работы мыши.
(_IDLE, _SELECTING, _MOVING, _RESIZING, _DRAWING, _IMG_MOVE, _IMG_RESIZE,
 _SIZING, _QUILL, _PICK_MOVE, _PICK_RESIZE, _NODE_DRAG) = range(12)

# На таком расстоянии от первого узла перо считает, что путь замыкают.
_QUILL_SNAP = 10

# Коды клавиш по раскладке США. При русской раскладке Qt отдаёт «я» вместо Z и
# «м» вместо V, поэтому сочетания сверяем с физической клавишей, а не с буквой.
_VK = {"A": 0x41, "C": 0x43, "P": 0x50, "S": 0x53, "V": 0x56, "Y": 0x59,
       "Z": 0x5A}


def _is_key(event, letter):
    """Нажата ли физическая клавиша с этой латинской буквой."""
    native = event.nativeVirtualKey()
    if native:
        return native == _VK[letter]
    # Без нативного кода (не Windows) сверяемся с самой буквой.
    return event.key() == getattr(Qt, "Key_" + letter)

# Инструменты, у которых курсор показывает будущий мазок кружком.
_BRUSH_TOOLS = ("pen", "marker", "eraser", "blur_brush")

# Сколько пикселей движения мыши прибавляют единицу толщины.
_SIZE_STEP = 6

# Вставленная картинка занимает столько от меньшей стороны выделения.
_IMAGE_FIT = 0.6

# Какой иконкой кнопка инструмента показывает выбранную форму.
_SHAPE_ICONS = {
    "rect": "shape_rect", "round": "shape_round", "ellipse": "shape_ellipse",
}
_BLUR_SHAPE_ICONS = {
    "rect": "blur_rect", "round": "blur_round", "ellipse": "blur_ellipse",
}
_BUCKET_ICONS = {"fill": "bucket", "unfill": "unbucket"}


# Больше этого по стороне не грузим: вставляют обычно логотип или вырезку, а
# фотография с телефона на 8000 px раздула бы память на пустом месте.
_IMAGE_MAX_SIDE = 4000


def _load_image(path):
    """QPixmap из файла или None. Слишком большие ужимаем при загрузке."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)          # учитываем поворот из EXIF
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > _IMAGE_MAX_SIDE:
        scaled = size.scaled(_IMAGE_MAX_SIDE, _IMAGE_MAX_SIDE, Qt.KeepAspectRatio)
        reader.setScaledSize(scaled)
    image = reader.read()
    if image.isNull():
        return None
    return QPixmap.fromImage(image)


def _editor_qss(color):
    """Поле ввода текста: пунктир той же нейтральной разметки, что и рамка."""
    return ("QLineEdit { background: rgba(0,0,0,90); border: 1px dashed %s;"
            " color: %s; padding: 2px 4px; }"
            % (theme.OVERLAY["line"], color))


class Overlay(QWidget):
    copy_requested  = Signal(QPixmap)
    save_requested  = Signal(QPixmap)
    print_requested = Signal(QPixmap)
    # Закрыт: (последняя рамка выделения в координатах экрана | None)
    closed = Signal(object)

    def __init__(self, shot, origin, settings, windows=()):
        super().__init__(None,
                         Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._shot = shot
        self._origin = origin          # левый верхний угол виртуального экрана
        self._settings = settings

        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setGeometry(QRect(origin, shot.size()))

        # --- состояние ------------------------------------------------- #
        self.selection = QRect()
        self._mode = _IDLE
        self._anchor = QPoint()        # неподвижный угол при выделении
        self._grab_offset = QPoint()   # смещение курсора внутри рамки при переносе
        self._resize_from = QRect()    # рамка на момент начала растяжки
        self._handle = ""
        self._editor_pos = QPoint()
        self._cursor_pos = QPoint(-1, -1)
        self._has_selection = False

        # Курсор: по умолчанию системная стрелка, перекрестие — по настройке.
        self._crosshair = bool(settings.get("crosshair_cursor", False))
        self.setCursor(self._idle_cursor())

        # Окна для подсветки приходят снаружи в экранных координатах: внутри
        # оверлея всё живёт со сдвигом на левый верхний угол снимка.
        self._highlight = bool(settings.get("highlight_windows", True))
        self._windows = [(hwnd, QRect(rect).translated(-origin))
                         for hwnd, rect in (windows or ())]
        self._hover_rect = None
        self._hover_hwnd = None

        self.shapes = []
        self._history = History()
        # Аннотации живут отдельным прозрачным слоем поверх снимка: только так
        # ластик может вычистить кусок нарисованного, не трогая сам кадр.
        self._layer = None
        self._layer_dirty = True
        self._draft = None
        self._quill = None             # незаконченный путь пера
        self._picked = None            # фигура под инструментом выбора
        self._pick_from = QRectF()     # её рамка на момент начала правки
        self._editing = False          # правим отдельные узлы выбранной фигуры
        self._node_id = None           # какой узел сейчас тянем
        self._tool = ""
        self._color = settings.get("draw_color", "#ff2d2d")
        self._width = int(settings.get("draw_width", 3))

        # Размытие: вид, сила и толщина кисти живут между съёмками, а размытые
        # копии снимка считаются лениво — при первом же мазке.
        self._blur_kind = settings.get("blur_kind", "pixel")
        self._blur_level = int(settings.get("blur_level", 2))
        self._blur_brush = int(settings.get("blur_brush", 4))
        self._eraser_width = int(settings.get("eraser_width", 4))
        self._size_from = QPoint()      # откуда потянули размер (Alt + ПКМ)
        self._size_start = 0
        self._size_anchor = QPoint()    # куда возвращаем курсор
        self._size_shift = 0            # накопленный сдвиг мыши
        self._blur_shape = settings.get("blur_shape", "rect")
        self._draw_shape = settings.get("draw_shape", "rect")
        self._bucket_mode = settings.get("bucket_mode", "fill")

        # Вставленная картинка, пока её двигают и растягивают. Она уже лежит в
        # списке фигур — активность нужна только для рамки с ручками.
        self._image = None
        self._image_from = QRectF()
        self._blur = BlurCache(shot)

        # --- панели ------------------------------------------------------ #
        self.tools = ToolPanel(self, self._color, self._blur_kind)
        self.tools.tool_picked.connect(self._set_tool)
        self.tools.color_clicked.connect(self._toggle_color_popup)
        self.tools.blur_clicked.connect(self._toggle_blur_popup)
        self.tools.image_clicked.connect(self.add_image)
        self.tools.variants_requested.connect(self._show_variants)
        self.tools.variant_scrolled.connect(self._scroll_variant)
        self._sync_tool_icons()
        self.tools.undo_clicked.connect(self.undo)
        self.tools.redo_clicked.connect(self.redo)
        self.tools.clear_clicked.connect(self.clear_all)
        self.tools.hide()

        self.actions_bar = ActionPanel(self)
        self.actions_bar.triggered.connect(self._on_action)
        self.actions_bar.hide()

        self._popup = None
        self._popup_kind = ""          # какая панелька открыта: color | blur
        self._editor = None            # QLineEdit инструмента «Текст»

        self._label_font = QFont("Segoe UI")
        self._label_font.setPixelSize(theme.s(12))

    # ------------------------------------------------------------------ #
    #  Запуск
    # ------------------------------------------------------------------ #
    def start(self, initial=None):
        """Показывает оверлей. initial — рамка в координатах экрана (или None)."""
        if initial is not None and not initial.isEmpty():
            rect = QRect(initial).translated(-self._origin)
            rect = rect.intersected(self.rect())
            if rect.width() > 4 and rect.height() > 4:
                self.selection = rect
                self._has_selection = True
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        if self._has_selection:
            self._show_panels()
        return self

    # ------------------------------------------------------------------ #
    #  Отрисовка
    # ------------------------------------------------------------------ #
    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._shot)

        sel = self._sel_norm()
        if sel.isEmpty():
            # Выделения ещё нет: подсвечиваем окно под курсором — оно выглядит
            # готовым к съёмке, остальной экран притушен.
            hover = self._hover_rect
            if hover is None:
                p.fillRect(self.rect(), QColor(0, 0, 0, DIM_ALPHA))
                self._paint_shapes(p, sel)
            else:
                self._paint_dim_around(p, hover)
                p.setRenderHint(QPainter.Antialiasing, False)
                p.setPen(QPen(QColor(theme.OVERLAY["line"]), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRect(hover.adjusted(1, 1, -2, -2))
                self._paint_size_label(p, hover)
            p.end()
            return

        self._paint_dim_around(p, sel)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._paint_shapes(p, sel)

        # Рамка и ручки.
        p.setRenderHint(QPainter.Antialiasing, False)
        self._paint_frame(p, sel)
        if self._mode not in (_SELECTING, _DRAWING):
            self._paint_handles(p, sel)

        self._paint_quill(p)
        self._paint_pick_frame(p)
        if self._image is not None:
            self._paint_image_frame(p)

        self._paint_size_label(p, sel)
        self._paint_brush_cursor(p)
        p.end()

    def _paint_brush_cursor(self, p):
        """Кружок размером с будущий мазок — как в фотошопе.

        Рисуем двумя окружностями, светлой поверх тёмной: одноцветная пропадала
        бы то на светлом кадре, то на тёмном."""
        radius = self._brush_radius()
        if radius is None or self._cursor_pos.x() < 0:
            return
        center = QPointF(self._size_from if self._mode == _SIZING
                         else self._cursor_pos)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.OVERLAY["line_under"]), 3))
        p.drawEllipse(center, radius, radius)
        p.setPen(QPen(QColor(theme.OVERLAY["line"]), 1))
        p.drawEllipse(center, radius, radius)
        # Точка в середине: без неё непонятно, куда именно придётся мазок.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.OVERLAY["line"]))
        p.drawEllipse(center, 1.2, 1.2)

    def _paint_image_frame(self, p):
        """Рамка с ручками вокруг вставленной картинки — та же разметка, что у
        выделения: пользователь уже знает, за что тянуть."""
        rect = self._image.rect.toRect()
        p.setRenderHint(QPainter.Antialiasing, False)
        self._paint_frame(p, rect)
        self._paint_handles(p, rect)

    def _paint_dim_around(self, p, rect):
        """Затемняет всё, кроме rect: четырьмя прямоугольниками — дешевле, чем
        регион с дыркой, и без швов по краям."""
        dim = QColor(0, 0, 0, DIM_ALPHA)
        w, h = self.width(), self.height()
        p.fillRect(QRect(0, 0, w, rect.top()), dim)
        p.fillRect(QRect(0, rect.bottom() + 1, w, h - rect.bottom() - 1), dim)
        p.fillRect(QRect(0, rect.top(), rect.left(), rect.height()), dim)
        p.fillRect(QRect(rect.right() + 1, rect.top(),
                         w - rect.right() - 1, rect.height()), dim)

    def _annotations(self):
        """Слой со всеми фигурами. Пересобирается только когда список менялся."""
        if self._layer is None or self._layer.size() != self._shot.size():
            self._layer = QPixmap(self._shot.size())
            self._layer_dirty = True
        if self._layer_dirty:
            self._layer.fill(Qt.transparent)
            # Картинку, которую сейчас двигают, в слой не кладём: она меняется
            # на каждое движение мыши, а пересборка слоя — это весь экран.
            skip = (self._image, self._picked)
            items = [sh for sh in self.shapes if sh not in skip]
            if items:
                p = QPainter(self._layer)
                try:
                    shapes_mod.draw_all(p, items, blur=self._blur)
                finally:
                    p.end()
            self._layer_dirty = False
        return self._layer

    def _invalidate_layer(self):
        self._layer_dirty = True

    def _paint_shapes(self, p, sel):
        """Фигуры рисуются по всему экрану, без обрезки по рамке — как в
        Lightshot: стрелку удобно вести к объекту снаружи, а обводку замыкать
        вокруг выделения. В файл всё равно уедет только выделенная область
        (см. result_pixmap)."""
        p.drawPixmap(0, 0, self._annotations())
        # Поверх слоя — то, что меняется прямо сейчас: незаконченная фигура и
        # картинка под рамкой. Класть их в слой пришлось бы на каждое движение
        # мыши, а это перерисовка всего экрана. Ластик — исключение: он правит
        # слой сразу, иначе стирания не видно.
        live = []
        if self._picked is not None:
            live.append(self._picked)
        if self._image is not None:
            live.append(self._image)
        if self._draft is not None and self._draft.kind != "eraser":
            live.append(self._draft)
        if live:
            shapes_mod.draw_all(p, live, blur=self._blur)

    def _paint_frame(self, p, sel):
        """Рамка «бегущими муравьями»: сплошная чёрная линия, поверх неё белый
        пунктир. Одноцветная рамка терялась бы то на светлом кадре, то на тёмном."""
        rect = sel.adjusted(0, 0, -1, -1)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.OVERLAY["line_under"]), 1))
        p.drawRect(rect)
        pen = QPen(QColor(theme.OVERLAY["line"]), 1)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern(theme.DASH)
        p.setPen(pen)
        p.drawRect(rect)

    def _paint_handles(self, p, sel):
        side = theme.s(HANDLE_SIZE)
        p.setPen(QPen(QColor(theme.OVERLAY["handle_edge"]), 1))
        p.setBrush(QColor(theme.OVERLAY["handle"]))
        for name in _HANDLES:
            r = self._handle_rect(sel, name, side)
            p.drawRect(r.adjusted(0, 0, -1, -1))

    def _paint_size_label(self, p, sel):
        text = "%d x %d" % (sel.width(), sel.height())
        fm = QFontMetrics(self._label_font)
        pad_x, pad_y = theme.s(7), theme.s(3)
        w = fm.horizontalAdvance(text) + pad_x * 2
        h = fm.height() + pad_y * 2
        gap = theme.s(6)

        x = sel.left()
        y = sel.top() - h - gap
        if y < 0:                       # у верхнего края — подпись уезжает внутрь
            y = sel.top() + gap
        x = max(0, min(x, self.width() - w))

        p.setRenderHint(QPainter.Antialiasing, True)
        bg = theme.color("panel")
        bg.setAlpha(235)
        p.setPen(QPen(QColor(theme.OVERLAY["line_under"]), 1))
        p.setBrush(bg)
        r = QRectF(x + 0.5, y + 0.5, w - 1, h - 1)
        p.drawRoundedRect(r, theme.s(5), theme.s(5))
        p.setFont(self._label_font)
        p.setPen(QPen(theme.color("text")))
        p.drawText(r, Qt.AlignCenter, text)

    # ------------------------------------------------------------------ #
    #  Геометрия
    # ------------------------------------------------------------------ #
    def _sel_norm(self):
        return self.selection.normalized() if self._has_selection else QRect()

    def _handle_rect(self, sel, name, side=None):
        side = side or theme.s(HANDLE_SIZE)
        fx, fy = _HANDLES[name]
        cx = sel.left() + int(round(sel.width() * fx))
        cy = sel.top() + int(round(sel.height() * fy))
        return QRect(cx - side // 2, cy - side // 2, side, side)

    def _handle_at(self, pos, rect=None):
        area = self._sel_norm() if rect is None else rect
        if area.isEmpty():
            return ""
        # Зона захвата шире самой ручки: попадать по 7 px мышью неудобно.
        side = theme.s(HANDLE_SIZE) + theme.s(5)
        for name in _HANDLES:
            if self._handle_rect(area, name, side).contains(pos):
                return name
        return ""

    def _clamp(self, pos):
        return QPoint(max(0, min(pos.x(), self.width() - 1)),
                      max(0, min(pos.y(), self.height() - 1)))

    # ------------------------------------------------------------------ #
    #  Мышь
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, e):
        pos = self._clamp(e.position().toPoint())

        if e.button() == Qt.RightButton:
            # Alt + правая кнопка — «резинка» толщины: тянешь вправо, инструмент
            # толстеет. Так размер меняют, не отрываясь от рисунка.
            if e.modifiers() & Qt.AltModifier and self._tool:
                self._mode = _SIZING
                self._size_from = pos
                self._size_anchor = e.globalPosition().toPoint()
                self._size_shift = 0
                self._size_start = self._tool_width()
                self.update()
                return
            # Сброс выделения по правой кнопке убран: одним случайным кликом
            # терялась вся работа. На пустом экране она по-прежнему закрывает
            # съёмку — там терять нечего.
            if not self._has_selection:
                self.cancel()
            return

        if e.button() != Qt.LeftButton:
            return

        self._close_popup()
        self._commit_text()

        if self._image is not None and self._press_on_image(pos):
            return

        handle = self._handle_at(pos)
        if handle:
            self._mode = _RESIZING
            self._handle = handle
            self._resize_from = QRect(self._sel_norm())
            self._hide_panels()
            return

        # Выбран инструмент — рисуем в любой точке экрана, хоть за рамкой.
        # Новое выделение в этом режиме не начинаем: инструмент сначала нужно
        # отключить (повторный клик по кнопке или Esc).
        if self._tool and self._has_selection:
            if self._tool == "bucket":
                # Ведро срабатывает по клику: тянуть им нечего.
                self._bucket_at(pos)
                return
            if self._tool == "quill":
                # Alt превращает перо в правку узлов: тянем сами точки и их
                # ручки, не добавляя новых.
                if e.modifiers() & Qt.AltModifier and self._grab_node(pos):
                    return
                self._quill_press(pos)
                return
            if self._tool == "select":
                if self._editing and self._grab_node(pos):
                    return
                self._pick_press(pos)
                return
            self._start_draw(pos)
            return

        sel = self._sel_norm()
        if self._has_selection and sel.contains(pos):
            self._mode = _MOVING
            self._grab_offset = pos - sel.topLeft()
            self._hide_panels()
            return

        # Клик вне выделения — начинаем новое. Но если в кадре уже что-то
        # нарисовано, новое выделение стёрло бы всю работу одним промахом мыши:
        # для этого есть отдельная кнопка «стереть всё».
        if self.shapes and self._has_selection:
            return
        self._mode = _SELECTING
        self._anchor = pos
        self.selection = QRect(pos, QSize(0, 0))
        self._has_selection = True
        self._hide_panels()
        self.update()

    def _press_on_image(self, pos):
        """Нажатие при активной картинке: ручка тянет, середина двигает, клик
        мимо фиксирует её и отдаёт событие обычной обработке."""
        rect = self._image.rect.toRect()
        handle = self._handle_at(pos, rect)
        if handle:
            self._history.push(self.shapes)
            self._mode = _IMG_RESIZE
            self._handle = handle
            self._image_from = QRectF(self._image.rect)
            self._hide_panels()
            return True
        if rect.contains(pos):
            self._history.push(self.shapes)
            self._mode = _IMG_MOVE
            self._grab_offset = pos - rect.topLeft()
            self._hide_panels()
            return True
        self._commit_image()
        return False

    # ------------------------------------------------------------------ #
    #  Выбор готовых элементов
    # ------------------------------------------------------------------ #
    def _pick_press(self, pos):
        """Клик инструментом выбора: за ручку — меняем размер, по фигуре —
        двигаем, мимо — снимаем выделение с элемента."""
        point = QPointF(pos)
        if self._picked is not None:
            bounds = shapes_mod.shape_bounds(self._picked).toRect()
            handle = self._handle_at(pos, bounds)
            if handle:
                self._history.push(self.shapes)
                self._mode = _PICK_RESIZE
                self._handle = handle
                self._pick_from = QRectF(bounds)
                return
            if shapes_mod.hit_shape(self._picked, point):
                self._history.push(self.shapes)
                self._mode = _PICK_MOVE
                self._grab_offset = pos
                return

        found = None
        for shape in reversed(self.shapes):     # верхняя фигура важнее нижних
            if shapes_mod.hit_shape(shape, point):
                found = shape
                break
        self._set_picked(found)
        if found is not None:
            self._history.push(self.shapes)
            self._mode = _PICK_MOVE
            self._grab_offset = pos

    def _set_picked(self, shape):
        if self._picked is shape:
            return
        self._picked = shape
        self._editing = False          # новый элемент — снова целиком
        # Выбранная фигура рисуется поверх слоя: её вот-вот начнут двигать.
        self._invalidate_layer()
        self.update()

    # --- правка отдельных узлов ------------------------------------------ #
    def _node_target(self):
        """Фигура, у которой сейчас показываются и правятся узлы."""
        if self._quill is not None:
            return self._quill
        if self._editing and self._picked is not None:
            return self._picked
        return None

    def _grab_node(self, pos):
        """Пробует зацепить узел под курсором. True — зацепили."""
        shape = self._node_target()
        if shape is None:
            return False
        handle = self._node_at(shape, pos)
        if handle is None:
            return False
        if shape is not self._quill:
            self._history.push(self.shapes)
        self._node_id = handle
        self._mode = _NODE_DRAG
        return True

    def _node_at(self, shape, pos):
        reach = theme.s(9)
        point = QPointF(pos)
        for handle_id, handle_point in shapes_mod.shape_handles(shape):
            if (abs(handle_point.x() - point.x()) <= reach
                    and abs(handle_point.y() - point.y()) <= reach):
                return handle_id
        return None

    def _drag_node(self, pos, symmetric=True):
        shape = self._node_target()
        if shape is None or self._node_id is None:
            return
        shapes_mod.move_handle(shape, self._node_id, QPointF(pos),
                               symmetric=symmetric)
        if shape is not self._quill:
            self._invalidate_layer()
        self.update()

    def _paint_nodes(self, p, shape):
        """Узлы и ручки правимой фигуры."""
        handles = shapes_mod.shape_handles(shape)
        if not handles:
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        side = theme.s(4)

        if isinstance(shape, shapes_mod.PathShape):
            # Ручки соединяем с их узлами — иначе непонятно, чьи они.
            p.setPen(QPen(QColor(theme.OVERLAY["line"]), 1))
            for (index, role), point in handles:
                if role:
                    p.drawLine(shape.nodes[index][0], point)

        for (_index, role), point in handles:
            p.setPen(QPen(QColor(theme.OVERLAY["line_under"]), 1))
            p.setBrush(QColor(theme.PALETTE["accent"] if role
                              else theme.OVERLAY["handle"]))
            if role:
                p.drawEllipse(point, side * 0.8, side * 0.8)
            else:
                p.drawRect(QRectF(point.x() - side, point.y() - side,
                                  side * 2, side * 2))

    def _pick_move(self, pos):
        delta = pos - self._grab_offset
        if delta.isNull():
            return
        shapes_mod.move_shape(self._picked, delta.x(), delta.y())
        self._grab_offset = pos
        self.update()

    def _pick_resize(self, pos, keep=False):
        target = self._resized_from(self._pick_from, pos, keep)
        source = shapes_mod.shape_bounds(self._picked)
        if source.width() <= 0 or source.height() <= 0:
            return
        shapes_mod.scale_shape(self._picked, source, target)
        self.update()

    def _resized_from(self, base, pos, keep=False):
        """Новая рамка при растягивании base за текущую ручку."""
        fx, fy = _HANDLES[self._handle]
        left, top = base.left(), base.top()
        right, bottom = base.right(), base.bottom()
        if fx == 0.0:
            left = pos.x()
        elif fx == 1.0:
            right = pos.x()
        if fy == 0.0:
            top = pos.y()
        elif fy == 1.0:
            bottom = pos.y()
        rect = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()
        if keep and base.height() > 0:
            aspect = base.width() / base.height()
            width = max(rect.width(), rect.height() * aspect)
            rect = QRectF(rect.left(), rect.top(), width, width / aspect)
        side = float(theme.s(12))
        if rect.width() < side:
            rect.setWidth(side)
        if rect.height() < side:
            rect.setHeight(side)
        return rect

    def _drop_picked(self):
        if self._picked is None:
            return
        self._history.push(self.shapes)
        if self._picked in self.shapes:
            self.shapes.remove(self._picked)
        self._picked = None
        self._sync_history()
        self.update()

    def _paint_pick_frame(self, p):
        if self._picked is None:
            return
        if self._editing:
            # В правке узлов рамка с ручками только мешает — она про масштаб.
            self._paint_nodes(p, self._picked)
            return
        bounds = shapes_mod.shape_bounds(self._picked).toRect()
        p.setRenderHint(QPainter.Antialiasing, False)
        self._paint_frame(p, bounds)
        self._paint_handles(p, bounds)

    # ------------------------------------------------------------------ #
    #  Перо
    # ------------------------------------------------------------------ #
    def _quill_press(self, pos):
        """Клик пером: первый ставит начало, следующие — узлы. Клик по первому
        узлу замыкает контур. Если после клика тянуть мышь, у узла появляется
        ручка и отрезок превращается в кривую — ровно как в Figma."""
        if self._quill is None:
            self._quill = shapes_mod.create("quill", self._color, self._width, pos)
            self._mode = _QUILL
            self._close_popup()
            self.update()
            return

        if self._quill_over_first(pos) and len(self._quill.nodes) > 1:
            self._quill.close_path()
            self._commit_quill()
            return

        self._quill.add_node(pos)
        self._mode = _QUILL
        self.update()

    def _quill_over_first(self, pos):
        """Курсор над первым узлом — там путь замыкают."""
        if self._quill is None:
            return False
        first = self._quill.first_point()
        return (abs(pos.x() - first.x()) <= _QUILL_SNAP
                and abs(pos.y() - first.y()) <= _QUILL_SNAP)

    def _quill_move(self, pos, dragging, alt=False):
        if self._quill is None:
            return
        if dragging:
            # Кнопка ещё зажата — тянем ручку последнего узла. Alt ломает
            # симметрию: входящая ручка остаётся, меняется только исходящая.
            self._quill.drag_handle(pos, symmetric=not alt)
            self._quill.preview = None
        else:
            self._quill.preview = QPointF(pos)
        self.update()

    def _commit_quill(self):
        """Закрепляет путь в кадре. Пустой (один узел) просто выбрасываем."""
        quill, self._quill = self._quill, None
        self._mode = _IDLE
        if quill is None:
            return
        quill.preview = None
        if quill.is_empty():
            self.update()
            return
        self._history.push(self.shapes)
        self.shapes.append(quill)
        self._sync_history()
        self.update()

    def _paint_quill(self, p):
        """Незаконченный путь: сама кривая, узлы и ручка последнего узла."""
        if self._quill is None:
            return
        shapes_mod.draw_all(p, [self._quill], blur=self._blur)

        p.setRenderHint(QPainter.Antialiasing, True)
        side = theme.s(4)
        snap = self._quill_over_first(self._cursor_pos)
        for index, node in enumerate(self._quill.nodes):
            point = node[0]
            for handle in (node[1], node[2]):
                if not (handle.x() or handle.y()):
                    continue
                end = QPointF(point.x() + handle.x(), point.y() + handle.y())
                p.setPen(QPen(QColor(theme.OVERLAY["line"]), 1))
                p.drawLine(point, end)
                p.setBrush(QColor(theme.OVERLAY["line"]))
                p.drawEllipse(end, side * 0.6, side * 0.6)

            # Первый узел подсвечивается, когда над ним курсор: это подсказка,
            # что клик замкнёт контур.
            highlight = index == 0 and snap and len(self._quill.nodes) > 1
            p.setPen(QPen(QColor(theme.OVERLAY["line_under"]), 1))
            p.setBrush(QColor(theme.PALETTE["accent"] if highlight
                              else theme.OVERLAY["handle"]))
            radius = side * (1.5 if highlight else 1.0)
            p.drawRect(QRectF(point.x() - radius, point.y() - radius,
                              radius * 2, radius * 2))

    def mouseMoveEvent(self, e):
        pos = self._clamp(e.position().toPoint())
        if self._mode != _SIZING:
            # При подборе толщины курсор мы держим на месте сами — обновлять
            # его позицию нельзя, иначе кружок прыгает вслед за возвратами.
            self._cursor_pos = pos
        mods = e.modifiers()
        # Shift — равные стороны, Alt — расти от точки нажатия во все стороны.
        shift = bool(mods & Qt.ShiftModifier)
        alt = bool(mods & Qt.AltModifier)

        if self._mode == _NODE_DRAG:
            # Правка узла важнее ведения пути: иначе перо перехватило бы
            # движение и вместо переноса точки тянуло бы новую ручку.
            self._drag_node(pos, symmetric=not alt)
            return
        if self._quill is not None:
            self._quill_move(pos, bool(e.buttons() & Qt.LeftButton), alt)
            return
        if self._mode == _SIZING:
            self._resize_tool(e)
            return
        if self._mode == _SELECTING:
            self.selection = QRect(self._anchor, pos).normalized()
            self.setCursor(self._drag_cursor(pos))
        elif self._mode == _RESIZING:
            self.selection = self._resized(pos)
        elif self._mode == _MOVING:
            sel = self._sel_norm()
            top_left = pos - self._grab_offset
            x = max(0, min(top_left.x(), self.width() - sel.width()))
            y = max(0, min(top_left.y(), self.height() - sel.height()))
            self.selection = QRect(QPoint(x, y), sel.size())
        elif self._mode == _PICK_MOVE and self._picked is not None:
            self._pick_move(pos)
        elif self._mode == _PICK_RESIZE and self._picked is not None:
            self._pick_resize(pos, keep=shift)
        elif self._mode == _IMG_MOVE and self._image is not None:
            size = self._image.rect.size()
            self._image.rect.moveTo(QPointF(pos - self._grab_offset))
            self._image.rect.setSize(size)
        elif self._mode == _IMG_RESIZE and self._image is not None:
            self._image.rect = self._resized_image(pos, keep=shift, center=alt)
        elif self._mode == _DRAWING and self._draft is not None:
            before = len(getattr(self._draft, "points", ()))
            self._draft.update_to(pos, square=shift, center=alt)
            if (self._draft.kind == "eraser"
                    and len(self._draft.points) != before):
                self._erase_tail(self._draft)
        else:
            self._sync_cursor(pos)
            self._update_hover(pos)

        self.update()

    def _update_hover(self, pos):
        """Окно под курсором. Ищем, только пока выделения нет: дальше подсветка
        мешала бы возиться с рамкой."""
        if not self._highlight or self._has_selection or self._tool:
            self._hover_rect = None
            self._hover_hwnd = None
            return
        self._hover_hwnd, self._hover_rect = self._window_at(pos)

    def _window_at(self, pos):
        for hwnd, rect in self._windows:
            if rect.contains(pos):
                return hwnd, rect
        return None, None

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton and self._mode == _SIZING:
            self._mode = _IDLE
            self.update()
            return
        if e.button() != Qt.LeftButton:
            return
        if self._mode == _QUILL:
            return
        if self._mode == _DRAWING:
            self._finish_draw()
        elif self._mode == _NODE_DRAG:
            self._node_id = None
            if self._quill is None:
                self._sync_history()
            self._show_panels()
        elif self._mode in (_PICK_MOVE, _PICK_RESIZE):
            self._sync_history()
            self._show_panels()
        elif self._mode in (_IMG_MOVE, _IMG_RESIZE):
            self._image.rect = self._image.rect.normalized()
            self._show_panels()
        elif self._mode in (_SELECTING, _RESIZING, _MOVING):
            sel = self._sel_norm()
            if sel.width() < 3 or sel.height() < 3:
                self._reset_selection()
            else:
                self.selection = sel
                self._show_panels()
        self._mode = _IDLE
        self._handle = ""
        self._sync_cursor(self._clamp(e.position().toPoint()))
        self.update()

    def wheelEvent(self, e):
        """Колесо перебирает формы активного инструмента — не отрываясь от
        рисования и не открывая селектор."""
        if self._scroll_variant(self._tool, e.angleDelta().y()):
            e.accept()
        else:
            e.ignore()

    def _scroll_variant(self, tool, delta):
        """Следующая или предыдущая форма инструмента. True — что-то сменили."""
        variants = self._tool_variants(tool)
        if variants is None:
            return False
        names, current, setter = variants
        step = 1 if delta < 0 else -1
        # Не по кругу: список упирается в края. Иначе после последней формы
        # неожиданно возвращается первая, и колесом легко проскочить нужную.
        index = max(0, min(names.index(current) + step, len(names) - 1))
        setter(names[index])
        if self._popup_kind == "variants" and self._popup is not None:
            self._popup.set_current(self._current_variant(tool))
        return True

    def _tool_variants(self, tool):
        """(список форм, текущая, функция выбора) или None у инструментов без
        вариантов."""
        if tool == "rect":
            return (list(shapes_mod.AREA_SHAPES), self._draw_shape,
                    self._set_draw_shape)
        if tool == "blur_rect":
            return (list(shapes_mod.BLUR_SHAPES), self._blur_shape,
                    self._set_blur_shape)
        if tool == "bucket":
            return (list(shapes_mod.BUCKET_MODES), self._bucket_mode,
                    self._set_bucket_mode)
        return None

    def _current_variant(self, tool):
        if tool == "rect":
            return self._draw_shape
        if tool == "bucket":
            return self._bucket_mode
        return self._blur_shape

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = self._clamp(e.position().toPoint())

        if self._tool == "select":
            # Двойной клик по элементу — правка его узлов, как в редакторах.
            if self._picked is not None and shapes_mod.hit_shape(
                    self._picked, QPointF(pos)):
                self._editing = True
                self.update()
            return

        # Двойной клик внутри выделения копирует — привычка из Lightshot.
        if self._has_selection and not self._tool and self._sel_norm().contains(pos):
            self._on_action("copy")
            return

        # Пустой экран: двойной клик по подсвеченному окну берёт его целиком.
        if not self._has_selection and self._hover_rect is not None:
            self.select_rect(self._hover_rect, self._hover_hwnd)

    def select_rect(self, rect, hwnd=None):
        """Ставит рамку по готовому прямоугольнику — так снимается целое окно."""
        rect = QRect(rect).intersected(self.rect())
        if rect.width() < 4 or rect.height() < 4:
            return
        if hwnd is not None:
            self._repaint_window(hwnd)
        self.selection = rect
        self._has_selection = True
        self._hover_rect = None
        self._mode = _IDLE
        self._show_panels()
        self._sync_cursor(self._cursor_pos)
        self.update()

    def _idle_cursor(self):
        """Обычное состояние: системная стрелка, если перекрестие не включено."""
        return Qt.CrossCursor if self._crosshair else Qt.ArrowCursor

    def _sync_cursor(self, pos):
        target = self._node_target()
        if target is not None and self._node_at(target, pos) is not None:
            self.setCursor(Qt.SizeAllCursor)
            return
        if self._picked is not None:
            bounds = shapes_mod.shape_bounds(self._picked).toRect()
            handle = self._handle_at(pos, bounds)
            if handle:
                self.setCursor(_HANDLE_CURSORS[handle])
                return
            if shapes_mod.hit_shape(self._picked, QPointF(pos)):
                self.setCursor(Qt.SizeAllCursor)
                return
        if self._brush_radius() is not None:
            # Системная стрелка поверх кружка только мешает целиться.
            self.setCursor(Qt.BlankCursor)
            return
        if self._image is not None:
            rect = self._image.rect.toRect()
            handle = self._handle_at(pos, rect)
            if handle:
                self.setCursor(_HANDLE_CURSORS[handle])
                return
            if rect.contains(pos):
                self.setCursor(Qt.SizeAllCursor)
                return
        handle = self._handle_at(pos)
        if handle:
            self.setCursor(_HANDLE_CURSORS[handle])
        elif (not self._tool and self._has_selection
                and self._sel_norm().contains(pos)):
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(self._idle_cursor())

    def _drag_cursor(self, pos):
        """Курсор протяжки — тот же, что Windows показывает при растягивании
        окна за угол; направление диагонали зависит от того, куда тянут."""
        if self._crosshair:
            return Qt.CrossCursor
        forward = ((pos.x() - self._anchor.x()) *
                   (pos.y() - self._anchor.y())) >= 0
        return Qt.SizeFDiagCursor if forward else Qt.SizeBDiagCursor

    def _resized_image(self, pos, keep=False, center=False):
        """Новый прямоугольник картинки.

        По умолчанию тянется свободно — и за угол, и за сторону. Shift держит
        пропорции, Alt растит от середины, как у фигур: одни и те же клавиши
        должны делать одно и то же везде.
        """
        r = QRectF(self._image_from)
        fx, fy = _HANDLES[self._handle]
        left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
        if fx == 0.0:
            left = pos.x()
        elif fx == 1.0:
            right = pos.x()
        if fy == 0.0:
            top = pos.y()
        elif fy == 1.0:
            bottom = pos.y()
        new = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()

        if keep:
            # Пропорция берётся у текущей рамки, а не у файла: «равномерно» —
            # значит как сейчас выглядит, даже если картинку уже сплющили.
            aspect = (self._image_from.width() / self._image_from.height()
                      if self._image_from.height() else self._image.aspect())
            width = max(new.width(), new.height() * aspect)
            height = width / aspect if aspect else new.height()
            # Тянем от противоположного края: он должен остаться на месте.
            anchor_x = r.right() if fx == 0.0 else r.left()
            anchor_y = r.bottom() if fy == 0.0 else r.top()
            new = QRectF(anchor_x - width if fx == 0.0 else anchor_x,
                         anchor_y - height if fy == 0.0 else anchor_y,
                         width, height)

        if center:
            middle = r.center()
            half_w = max(abs(new.left() - middle.x()), abs(new.right() - middle.x()))
            half_h = max(abs(new.top() - middle.y()), abs(new.bottom() - middle.y()))
            if keep:
                aspect = (self._image_from.width() / self._image_from.height()
                          if self._image_from.height() else self._image.aspect())
                half_w = max(half_w, half_h * aspect)
                half_h = half_w / aspect if aspect else half_h
            new = QRectF(middle.x() - half_w, middle.y() - half_h,
                         half_w * 2, half_h * 2)

        side = float(theme.s(16))
        if new.width() < side:
            new.setWidth(side)
        if new.height() < side:
            new.setHeight(side)
        return new

    def _resized(self, pos):
        """Новая рамка при растяжке: ручка двигает только «свои» стороны, чтобы
        боковая (t/b/l/r) не схлопывала вторую ось."""
        r = QRect(self._resize_from)
        fx, fy = _HANDLES[self._handle]
        if fx == 0.0:
            r.setLeft(pos.x())
        elif fx == 1.0:
            r.setRight(pos.x())
        if fy == 0.0:
            r.setTop(pos.y())
        elif fy == 1.0:
            r.setBottom(pos.y())
        return r.normalized()

    # ------------------------------------------------------------------ #
    #  Рисование
    # ------------------------------------------------------------------ #
    def _resize_tool(self, event):
        """Толщина по горизонтальному движению мыши.

        Курсор возвращаем в точку, где нажали: иначе он уползает через
        полэкрана. Кружок при этом рисуется там же и не дёргается — его центр
        зафиксирован на время подбора, а не следует за событиями мыши.
        """
        global_pos = event.globalPosition().toPoint()
        delta = global_pos.x() - self._size_anchor.x()
        if not delta:
            return                      # это наш же возврат курсора, не движение
        self._size_shift += delta
        self._set_tool_width(self._size_start + self._size_shift // _SIZE_STEP)

        from PySide6.QtGui import QCursor
        QCursor.setPos(self._size_anchor)
        self.update()

    def _tool_width(self):
        """Толщина активного инструмента: у ластика и кисти размытия своя."""
        if self._tool == "eraser":
            return self._eraser_width
        if self._tool == "blur_brush":
            return self._blur_brush
        return self._width

    def _set_tool_width(self, value):
        value = max(1, min(20, int(value)))
        if self._tool == "eraser":
            self._eraser_width = value
            self._settings["eraser_width"] = value
        elif self._tool == "blur_brush":
            self._blur_brush = value
            self._settings["blur_brush"] = value
        else:
            self._width = value
            self._settings["draw_width"] = value

    def _brush_radius(self):
        """Радиус кружка-подсказки под курсором или None."""
        if self._mode == _SIZING or self._tool in _BRUSH_TOOLS:
            width = self._tool_width()
            if self._tool == "eraser":
                width = shapes_mod.eraser_width(width)
            elif self._tool == "blur_brush":
                width = shapes_mod.blur_brush_width(width)
            elif self._tool == "marker":
                # Маркер рисует полосой в несколько толщин линии — кружок
                # обязан показывать именно её, иначе он врёт вчетверо.
                width = shapes_mod.marker_width(width)
            return max(2.0, width / 2.0)
        return None

    def _set_tool(self, name):
        self._commit_text()
        self._commit_image()
        self._commit_quill()
        if name != "select":
            self._set_picked(None)
        self._tool = name or ""
        self._settings["last_tool"] = self._tool or self._settings.get("last_tool")
        self._close_popup()
        self._sync_cursor(self._cursor_pos)

    def _start_draw(self, pos):
        if self._tool == "text":
            self._open_text_editor(pos)
            return
        if self._tool == "eraser":
            self._annotations()          # слой должен быть собран до стирания
        width = self._tool_width()
        self._draft = shapes_mod.create(self._tool, self._color, width, pos,
                                        self._blur_kind, self._blur_level,
                                        self._blur_shape, self._draw_shape)
        self._mode = _DRAWING
        # Панели не прячем: в Lightshot они на месте всё время рисования, а
        # мигание на каждый штрих раздражает сильнее, чем закрытый ими угол.
        self._close_popup()

    def _erase_tail(self, shape):
        """Стирает последний отрезок мазка прямо в слое."""
        layer = self._annotations()
        p = QPainter(layer)
        try:
            shape.erase(p, shape.tail_path())
        finally:
            p.end()

    def _finish_draw(self):
        if self._draft is not None and not self._draft.is_empty():
            self._history.push(self.shapes)
            self.shapes.append(self._draft)
        self._draft = None
        self._sync_history()

    def undo(self):
        if self._editor is not None:
            self._cancel_text()
            return
        if self._history.undo(self.shapes):
            self.update()
        self._after_history()

    def redo(self):
        """Повтор доступен, пока не сделано новое изменение: любое действие
        обрывает ветку отменённого — так везде, и так понятнее."""
        if self._history.redo(self.shapes):
            self.update()
        self._after_history()

    def _after_history(self):
        """Отмена не должна отбирать выбранное: если элемент остался в кадре,
        рамка с ручками остаётся на нём — иначе после Ctrl+Z его уже не
        подвинуть."""
        if self._image is not None and self._image not in self.shapes:
            self._image = None
        if self._picked is not None and self._picked not in self.shapes:
            self._picked = None
        self._sync_history()

    def clear_all(self):
        """Убирает всё нарисованное. Нужна, чтобы выделить новую область: клик
        мимо рамки нарочно ничего не стирает."""
        if not self.shapes:
            return
        self._history.push(self.shapes)
        self.shapes.clear()
        self._image = None
        self._picked = None
        self._draft = None
        self._sync_history()
        self.update()

    def _sync_history(self):
        self._invalidate_layer()
        self.tools.set_undo_enabled(self._history.can_undo())
        self.tools.set_redo_enabled(self._history.can_redo())
        self.tools.set_clear_enabled(bool(self.shapes))

    # --- текст ---------------------------------------------------------- #
    def _open_text_editor(self, pos):
        self._commit_text()
        size = shapes_mod.text_size_for(self._width)
        ed = QLineEdit(self)
        f = QFont("Segoe UI")
        f.setPixelSize(size)
        f.setBold(True)
        ed.setFont(f)
        ed.setStyleSheet(_editor_qss(self._color))
        ed.setMinimumWidth(theme.s(120))
        ed.move(pos)
        ed.returnPressed.connect(self._commit_text)
        ed.textChanged.connect(self._grow_editor)
        ed.show()
        ed.setFocus(Qt.OtherFocusReason)
        self._editor = ed
        self._editor_pos = QPoint(pos)

    def _grow_editor(self, text):
        if self._editor is None:
            return
        fm = QFontMetrics(self._editor.font())
        w = max(theme.s(120), fm.horizontalAdvance(text) + theme.s(24))
        self._editor.resize(w, fm.height() + theme.s(10))

    def _commit_text(self):
        ed, self._editor = self._editor, None
        if ed is None:
            return
        text = ed.text().strip()
        ed.deleteLater()
        if text:
            # Смещение к базовой линии: QLineEdit рисует текст с отступом, и без
            # поправки готовая надпись прыгала бы вверх-влево относительно поля.
            pos = QPoint(self._editor_pos.x() + theme.s(4),
                         self._editor_pos.y() + theme.s(4))
            shape = shapes_mod.TextShape(self._color, self._width, pos, text)
            self._history.push(self.shapes)
            self.shapes.append(shape)
            self._sync_history()
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    def _cancel_text(self):
        ed, self._editor = self._editor, None
        if ed is not None:
            ed.deleteLater()
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    # --- цвет ------------------------------------------------------------ #
    def _toggle_color_popup(self):
        # Повторный клик по своей кнопке закрывает панельку, клик по соседней —
        # подменяет её, а не оставляет обе висеть.
        if self._popup_kind == "color":
            self._close_popup()
            return
        self._close_popup()
        pop = ColorPopup(self, self._color, self._width)
        pop.color_picked.connect(self._set_color)
        pop.width_picked.connect(self._set_width)
        self._show_popup(pop, "color", self.tools.color_btn)

    def _toggle_blur_popup(self):
        if self._popup_kind == "blur":
            self._close_popup()
            return
        self._close_popup()
        pop = BlurPopup(self, self._blur_kind, self._blur_level)
        pop.kind_picked.connect(self._set_blur_kind)
        pop.level_picked.connect(self._set_blur_level)
        self._show_popup(pop, "blur", self.tools.blur_btn)

    def _show_popup(self, pop, kind, anchor):
        pop.closed.connect(self._close_popup)
        top_right = self.tools.mapTo(self, QPoint(0, anchor.y()))
        pop.popup_at(QPoint(top_right.x() - theme.s(6), top_right.y()))
        self._popup = pop
        self._popup_kind = kind

    def _close_popup(self):
        pop, self._popup = self._popup, None
        self._popup_kind = ""
        if pop is not None:
            pop.hide()
            pop.deleteLater()

    def _set_color(self, name):
        self._color = name
        self._settings["draw_color"] = name
        self.tools.set_color(name)
        if self._editor is not None:
            self._editor.setStyleSheet(_editor_qss(name))

    def _set_width(self, w):
        self._width = int(w)
        self._settings["draw_width"] = int(w)

    def _set_draw_shape(self, shape):
        """Форма контурной фигуры применяется к следующей — уже нарисованную не
        перекроить."""
        self._draw_shape = shape
        self._settings["draw_shape"] = shape
        self._sync_tool_icons()

    # --- выбор формы у самой кнопки --------------------------------------- #
    def _sync_tool_icons(self):
        """Кнопки инструментов показывают выбранную форму — иначе после выбора
        не видно, что нарисуется."""
        # Значение из конфига может быть от прошлой версии программы — иконку
        # берём с запасным вариантом, иначе оверлей падал бы на ровном месте.
        self.tools.set_tool_icon(
            "rect", _SHAPE_ICONS.get(self._draw_shape, "shape_rect"))
        self.tools.set_tool_icon(
            "blur_rect", _BLUR_SHAPE_ICONS.get(self._blur_shape, "blur_rect"))
        self.tools.set_tool_icon(
            "bucket", _BUCKET_ICONS.get(self._bucket_mode, "bucket"))

    def _show_variants(self, tool):
        """Повторный клик по кнопке инструмента выдвигает формы сбоку от неё."""
        self._close_popup()
        if tool == "rect":
            items = [(name, _SHAPE_ICONS[name]) for name in shapes_mod.AREA_SHAPES]
            current, setter = self._draw_shape, self._set_draw_shape
        elif tool == "bucket":
            items = [(name, _BUCKET_ICONS[name])
                     for name in shapes_mod.BUCKET_MODES]
            current, setter = self._bucket_mode, self._set_bucket_mode
        else:
            items = [(name, _BLUR_SHAPE_ICONS[name])
                     for name in shapes_mod.BLUR_SHAPES]
            current, setter = self._blur_shape, self._set_blur_shape

        button = self.tools.tool_button(tool)
        if button is None:
            return
        pop = Flyout(self, items, current)
        pop.picked.connect(setter)
        pop.closed.connect(self._close_popup)
        anchor = QRect(self.tools.mapTo(self, button.pos()), button.size())
        pop.slide_from(anchor)
        self._popup = pop
        self._popup_kind = "variants"

    def _set_bucket_mode(self, mode):
        self._bucket_mode = mode
        self._settings["bucket_mode"] = mode
        self._sync_tool_icons()

    # --- заливка ----------------------------------------------------------- #
    def _bucket_at(self, pos):
        """Клик ведром: залить область под курсором или снять заливку с неё."""
        if self._bucket_mode == "unfill":
            self._remove_fill(pos)
            return
        area = self._sel_norm().intersected(self.rect())
        if area.isEmpty() or not area.contains(pos):
            return

        # Заливаем строго по нарисованному: границы ищем в слое аннотаций, а
        # сам снимок ведро не касается — иначе оно цеплялось бы за контрасты
        # интерфейса под ним.
        mask, share = fill_mod.flood_mask(self._annotations(), area, pos)
        if mask is None:
            # Контур дырявый — краска ушла бы на всё выделение.
            self._toast_leak(share)
            return
        pixmap = fill_mod.colorize(mask, self._color)
        self._history.push(self.shapes)
        self.shapes.append(shapes_mod.FillShape(pixmap, QRectF(area), self._color))
        self._sync_history()
        self.update()

    def _remove_fill(self, pos):
        """Снимает заливку под курсором — не трогая остальную историю."""
        point = QPointF(pos)
        for shape in reversed(self.shapes):
            if shape.kind == "fill" and shape.contains(point):
                self._history.push(self.shapes)
                self.shapes.remove(shape)
                self._sync_history()
                self.update()
                return

    def _toast_leak(self, share):
        """Сообщение о неудачной заливке. Тихо ничего не делать нельзя: со
        стороны это выглядит как сломанная кнопка."""
        del share
        from .toast import show as show_toast
        show_toast(tr("Nothing to fill here"), icon_name="info")

    # --- размытие --------------------------------------------------------- #
    def _set_blur_kind(self, kind):
        self._blur_kind = kind
        self._settings["blur_kind"] = kind
        self.tools.set_blur_kind(kind)
        self._reblur_draft()

    def _set_blur_level(self, level):
        self._blur_level = int(level)
        self._settings["blur_level"] = int(level)
        self._reblur_draft()

    def _set_blur_shape(self, shape):
        """Форма применяется к следующей области — уже нарисованную не
        перекроить."""
        self._blur_shape = shape
        self._settings["blur_shape"] = shape
        self._sync_tool_icons()

    def _reblur_draft(self):
        """Смена вида или силы перерисовывает последнюю фигуру размытия: иначе
        пришлось бы отменять её и рисовать заново, чтобы увидеть разницу."""
        for shape in reversed(self.shapes):
            if shape.kind in shapes_mod.BLUR_TOOLS:
                shape.blur_kind = self._blur_kind
                shape.blur_level = self._blur_level
                break
        self.update()

    # ------------------------------------------------------------------ #
    #  Вставленная картинка
    # ------------------------------------------------------------------ #
    def add_image(self):
        """Выбирает файл и кладёт картинку поверх снимка — сразу с рамкой, чтобы
        можно было двигать и растягивать."""
        self._commit_image()
        self._commit_text()
        self._close_popup()

        # Диалог делаем дочерним окном оверлея: тогда он всплывает поверх, и
        # прятать оверлей не нужно — выделение и рисунки остаются на виду.
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Choose image"), "",
            "%s (*.png *.jpg *.jpeg *.bmp *.gif *.webp)" % tr("Image files"))
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        if not path:
            return

        pixmap = _load_image(path)
        if pixmap is None:
            self._image = None
            return

        self._history.push(self.shapes)
        self.shapes.append(shapes_mod.ImageShape(pixmap, self._image_start(pixmap)))
        self._image = self.shapes[-1]
        self._sync_history()
        self._invalidate_layer()
        self._show_panels()
        self.update()

    def _image_start(self, pixmap):
        """Куда положить картинку: по центру выделения, вписав в его долю."""
        area = self._sel_norm() if self._has_selection else self.rect()
        limit_w = area.width() * _IMAGE_FIT
        limit_h = area.height() * _IMAGE_FIT
        width, height = float(pixmap.width()), float(pixmap.height())
        scale = min(1.0, limit_w / width, limit_h / height)
        width *= scale
        height *= scale
        return QRectF(area.center().x() - width / 2.0,
                      area.center().y() - height / 2.0, width, height)

    def _commit_image(self):
        """Снимает рамку: картинка остаётся в кадре как обычная фигура."""
        if self._image is None:
            return
        self._image = None
        self._invalidate_layer()      # теперь она рисуется вместе с остальными
        self.update()

    def _drop_image(self):
        """Удаляет активную картинку целиком (Delete)."""
        if self._image is None:
            return
        if self._image in self.shapes:
            self._history.push(self.shapes)
            self.shapes.remove(self._image)
        self._image = None
        self._sync_history()
        self.update()

    # ------------------------------------------------------------------ #
    #  Панели
    # ------------------------------------------------------------------ #
    def _screen_area(self, rect):
        """Границы монитора, на котором лежит rect, в координатах оверлея.

        Панели держим в пределах одного экрана: у выделения на левом мониторе
        «справа» — это соседний монитор, и панель уезжала бы туда, а то и за
        край рабочего стола."""
        from PySide6.QtGui import QGuiApplication
        center = rect.center() + self._origin
        screen = QGuiApplication.screenAt(center)
        if screen is None:
            return QRect(self.rect())
        # Пересечение с самим оверлеем обязательно: монитор мог отдать границы,
        # которых в снимке нет (разные раскладки экранов), и панель уехала бы
        # за край окна, где её уже не нажать.
        return screen.geometry().translated(-self._origin).intersected(self.rect())

    def _show_panels(self):
        if not self._has_selection:
            return
        sel = self._sel_norm()
        gap = theme.s(6)
        area = self._screen_area(sel)

        tp, ap = self.tools, self.actions_bar
        # Инструменты всегда у правого края рамки: снаружи, а если справа уже
        # край экрана — внутрь той же стенки. Прыжок на другую сторону сбивает:
        # рука тянется туда, где панель была секунду назад.
        x = sel.right() + gap
        if x + tp.width() > area.right():
            x = sel.right() - tp.width() - gap
        x = max(area.left(), min(x, area.right() - tp.width()))

        y = sel.top()
        # У выделения впритык к нижнему краю панель не должна вылезать за экран.
        y = max(area.top(), min(y, area.bottom() - tp.height()))
        tp.move(int(x), int(y))

        # Действия — под рамкой; у нижнего края экрана уходят внутрь неё, по
        # той же причине, что и инструменты.
        ay = sel.bottom() + gap
        if ay + ap.height() > area.bottom():
            ay = sel.bottom() - ap.height() - gap
        ay = max(area.top(), min(ay, area.bottom() - ap.height()))

        ax = sel.right() - ap.width()
        ax = max(area.left(), min(ax, area.right() - ap.width()))
        ap.move(int(ax), int(ay))

        self._sync_history()
        tp.show()
        tp.raise_()
        ap.show()
        ap.raise_()

    def _hide_panels(self):
        self._close_popup()
        self.tools.hide()
        self.actions_bar.hide()

    def _reset_selection(self):
        self._commit_image()
        self._commit_quill()
        self._has_selection = False
        self.selection = QRect()
        self._update_hover(self._cursor_pos)
        self.shapes.clear()
        self._draft = None
        self._cancel_text()
        self._hide_panels()
        self.update()

    def _repaint_window(self, hwnd):
        """Просит окно нарисовать себя заново и вклеивает результат в снимок.

        Иначе в кадр попадёт всё, что лежало поверх окна в момент съёмки:
        общий снимок экрана видит только верхний слой. Не получилось (окно с
        чужими правами, ускоренный вывод) — молча остаёмся с тем, что сняли.
        """
        shot = capture.grab_window(hwnd)
        if shot is None:
            return False
        pixmap, frame = shot
        target = QRect(frame).translated(-self._origin)
        painter = QPainter(self._shot)
        try:
            painter.drawPixmap(target.topLeft(), pixmap)
        finally:
            painter.end()
        # Снимок изменился — размытые копии по нему больше не годятся.
        self._blur.set_source(self._shot)
        return True

    # ------------------------------------------------------------------ #
    #  Клавиатура
    # ------------------------------------------------------------------ #
    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()

        if key == Qt.Key_Escape:
            # Esc разбирает состояние по слоям: сначала текст, потом палитра,
            # потом инструмент, и только затем закрывает съёмку.
            if self._editor is not None:
                self._cancel_text()
            elif self._editing:
                self._editing = False
                self.update()
            elif self._picked is not None:
                self._set_picked(None)
            elif self._quill is not None:
                self._commit_quill()
            elif self._image is not None:
                self._commit_image()
            elif self._popup is not None:
                self._close_popup()
            elif self._tool:
                self.tools.set_tool(None)
                self._set_tool("")
            else:
                self.cancel()
            return

        if mods & Qt.ControlModifier:
            if _is_key(e, "Z"):
                # Ctrl+Shift+Z и Ctrl+Y — оба привычные сочетания для повтора.
                self.redo() if mods & Qt.ShiftModifier else self.undo()
                return
            if _is_key(e, "Y"):
                self.redo()
                return
            if _is_key(e, "C"):
                self._on_action("copy")
                return
            if _is_key(e, "S"):
                self._on_action("save")
                return
            if _is_key(e, "P"):
                self._on_action("print")
                return
            if _is_key(e, "A"):
                self.selection = QRect(self.rect())
                self._has_selection = True
                self._show_panels()
                self.update()
                return

        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            if self._quill is not None:
                if not self._quill.drop_node():
                    self._quill = None    # убрали последний — пути больше нет
                    self._mode = _IDLE
                self.update()
                return
            if self._picked is not None:
                self._drop_picked()
                return
            if self._image is not None:
                self._drop_image()
                return

        if _is_key(e, "V") and mods == Qt.NoModifier:
            self.tools.set_tool("select")
            self._set_tool("select")
            return

        if key in (Qt.Key_Return, Qt.Key_Enter) and self._editor is None:
            if self._quill is not None:
                self._commit_quill()      # Enter заканчивает незамкнутый путь
                return
            self._on_action("copy")
            return

        super().keyPressEvent(e)

    # ------------------------------------------------------------------ #
    #  Действия
    # ------------------------------------------------------------------ #
    def result_pixmap(self):
        """Готовый снимок выделенной области вместе с аннотациями."""
        self._commit_text()
        self._commit_image()
        self._commit_quill()
        sel = self._sel_norm().intersected(self.rect())
        if sel.width() < 1 or sel.height() < 1:
            return None
        pm = self._shot.copy(sel)
        if self.shapes:
            p = QPainter(pm)
            try:
                # Слой уже собран и обрезается самим копированием — отдельная
                # отрисовка фигур с клипом больше не нужна.
                p.drawPixmap(0, 0, self._annotations(), sel.x(), sel.y(),
                             sel.width(), sel.height())
            finally:
                p.end()
        return pm

    def _on_action(self, name):
        if name == "close":
            self.cancel()
            return
        pm = self.result_pixmap()
        if pm is None:
            return
        self._hide_panels()
        if name == "copy":
            self.copy_requested.emit(pm)
        elif name == "save":
            self.save_requested.emit(pm)
        elif name == "print":
            self.print_requested.emit(pm)

    def finish(self):
        """Закрыть оверлей, сохранив рамку для следующего снимка."""
        rect = None
        if self._has_selection:
            sel = self._sel_norm()
            if sel.width() > 4 and sel.height() > 4:
                rect = QRect(sel).translated(self._origin)
        self._hide_panels()
        self.closed.emit(rect)
        self.close()

    def cancel(self):
        self._cancel_text()
        self.finish()

    def closeEvent(self, e):
        self._close_popup()
        super().closeEvent(e)
