"""
Оверлей съёмки: затемнённый снимок рабочего стола, рамка выделения, панели
инструментов и рисование поверх выделенной области.

Одно окно на весь виртуальный рабочий стол (все мониторы сразу), поэтому
координаты внутри — это координаты снимка со сдвигом на левый верхний угол
виртуального экрана. Никакого DPI-масштабирования: приложение стартует с
QT_ENABLE_HIGHDPI_SCALING=0, логический пиксель равен физическому.
"""

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import QLineEdit, QWidget

from ..core import windows as win_utils
from ..core.constants import DIM_ALPHA, HANDLE_SIZE
from . import shapes as shapes_mod
from . import theme
from .colorpop import ColorPopup
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
_IDLE, _SELECTING, _MOVING, _RESIZING, _DRAWING = range(5)


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

        self.shapes = []
        self._draft = None
        self._tool = ""
        self._color = settings.get("draw_color", "#ff2d2d")
        self._width = int(settings.get("draw_width", 3))

        # --- панели ------------------------------------------------------ #
        self.tools = ToolPanel(self, self._color)
        self.tools.tool_picked.connect(self._set_tool)
        self.tools.color_clicked.connect(self._toggle_color_popup)
        self.tools.undo_clicked.connect(self.undo)
        self.tools.hide()

        self.actions_bar = ActionPanel(self)
        self.actions_bar.triggered.connect(self._on_action)
        self.actions_bar.hide()

        self._popup = None
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

        self._paint_size_label(p, sel)
        p.end()

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

    def _paint_shapes(self, p, sel):
        """Фигуры рисуются по всему экрану, без обрезки по рамке — как в
        Lightshot: стрелку удобно вести к объекту снаружи, а обводку замыкать
        вокруг выделения. В файл всё равно уедет только выделенная область
        (см. result_pixmap)."""
        items = list(self.shapes)
        if self._draft is not None:
            items.append(self._draft)
        if items:
            shapes_mod.draw_all(p, items)

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

    def _handle_at(self, pos):
        sel = self._sel_norm()
        if sel.isEmpty():
            return ""
        # Зона захвата шире самой ручки: попадать по 7 px мышью неудобно.
        side = theme.s(HANDLE_SIZE) + theme.s(5)
        for name in _HANDLES:
            if self._handle_rect(sel, name, side).contains(pos):
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
            # Как в Lightshot: правая кнопка сначала сбрасывает выделение, а на
            # пустом экране закрывает съёмку.
            if self._has_selection:
                self._reset_selection()
            else:
                self.cancel()
            return

        if e.button() != Qt.LeftButton:
            return

        self._close_popup()
        self._commit_text()

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
            self._start_draw(pos)
            return

        sel = self._sel_norm()
        if self._has_selection and sel.contains(pos):
            self._mode = _MOVING
            self._grab_offset = pos - sel.topLeft()
            self._hide_panels()
            return

        # Клик вне выделения — начинаем новое.
        self._mode = _SELECTING
        self._anchor = pos
        self.selection = QRect(pos, QSize(0, 0))
        self._has_selection = True
        self.shapes.clear()
        self._hide_panels()
        self.update()

    def mouseMoveEvent(self, e):
        pos = self._clamp(e.position().toPoint())
        self._cursor_pos = pos
        shift = bool(e.modifiers() & Qt.ShiftModifier)

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
        elif self._mode == _DRAWING and self._draft is not None:
            self._draft.update_to(pos, square=shift)
        else:
            self._sync_cursor(pos)
            self._update_hover(pos)

        self.update()

    def _update_hover(self, pos):
        """Окно под курсором. Ищем, только пока выделения нет: дальше подсветка
        мешала бы возиться с рамкой."""
        if not self._highlight or self._has_selection or self._tool:
            self._hover_rect = None
            return
        self._hover_rect = win_utils.window_at(pos, self._windows)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._mode == _DRAWING:
            self._finish_draw()
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

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = self._clamp(e.position().toPoint())

        # Двойной клик внутри выделения копирует — привычка из Lightshot.
        if self._has_selection and not self._tool and self._sel_norm().contains(pos):
            self._on_action("copy")
            return

        # Пустой экран: двойной клик по подсвеченному окну берёт его целиком.
        if not self._has_selection and self._hover_rect is not None:
            self.select_rect(self._hover_rect)

    def select_rect(self, rect):
        """Ставит рамку по готовому прямоугольнику — так снимается целое окно."""
        rect = QRect(rect).intersected(self.rect())
        if rect.width() < 4 or rect.height() < 4:
            return
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
    def _set_tool(self, name):
        self._commit_text()
        self._tool = name or ""
        self._settings["last_tool"] = self._tool or self._settings.get("last_tool")
        self._sync_cursor(self._cursor_pos)

    def _start_draw(self, pos):
        if self._tool == "text":
            self._open_text_editor(pos)
            return
        self._draft = shapes_mod.create(self._tool, self._color, self._width, pos)
        self._mode = _DRAWING
        # Панели не прячем: в Lightshot они на месте всё время рисования, а
        # мигание на каждый штрих раздражает сильнее, чем закрытый ими угол.
        self._close_popup()

    def _finish_draw(self):
        if self._draft is not None and not self._draft.is_empty():
            self.shapes.append(self._draft)
        self._draft = None
        self.tools.set_undo_enabled(bool(self.shapes))

    def undo(self):
        if self._editor is not None:
            self._cancel_text()
            return
        if self.shapes:
            self.shapes.pop()
            self.update()
        self.tools.set_undo_enabled(bool(self.shapes))

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
            self.shapes.append(shape)
            self.tools.set_undo_enabled(True)
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
        if self._popup is not None:
            self._close_popup()
            return
        pop = ColorPopup(self, self._color, self._width)
        pop.color_picked.connect(self._set_color)
        pop.width_picked.connect(self._set_width)
        pop.closed.connect(self._close_popup)
        top_right = self.tools.mapTo(self, QPoint(0, self.tools.color_btn.y()))
        pop.popup_at(QPoint(top_right.x() - theme.s(6), top_right.y()))
        self._popup = pop

    def _close_popup(self):
        pop, self._popup = self._popup, None
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

    # ------------------------------------------------------------------ #
    #  Панели
    # ------------------------------------------------------------------ #
    def _show_panels(self):
        if not self._has_selection:
            return
        sel = self._sel_norm()
        gap = theme.s(6)

        tp, ap = self.tools, self.actions_bar
        # Инструменты — справа от рамки; не влезли — слева; не влезли и там —
        # внутрь у правого края.
        x = sel.right() + gap
        if x + tp.width() > self.width():
            x = sel.left() - gap - tp.width()
        if x < 0:
            x = max(0, sel.right() - tp.width() - gap)
        y = sel.top()
        y = max(0, min(y, self.height() - tp.height()))
        tp.move(int(x), int(y))

        # Действия — под рамкой; не влезли — над; не влезли и там — внутрь снизу.
        ay = sel.bottom() + gap
        if ay + ap.height() > self.height():
            ay = sel.top() - gap - ap.height()
        if ay < 0:
            ay = max(0, sel.bottom() - ap.height() - gap)
        ax = sel.right() - ap.width()
        ax = max(0, min(ax, self.width() - ap.width()))
        ap.move(int(ax), int(ay))

        tp.set_undo_enabled(bool(self.shapes))
        tp.show()
        tp.raise_()
        ap.show()
        ap.raise_()

    def _hide_panels(self):
        self._close_popup()
        self.tools.hide()
        self.actions_bar.hide()

    def _reset_selection(self):
        self._has_selection = False
        self.selection = QRect()
        self._update_hover(self._cursor_pos)
        self.shapes.clear()
        self._draft = None
        self._cancel_text()
        self._hide_panels()
        self.update()

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
            elif self._popup is not None:
                self._close_popup()
            elif self._tool:
                self.tools.set_tool(None)
                self._set_tool("")
            else:
                self.cancel()
            return

        if mods & Qt.ControlModifier:
            if key == Qt.Key_Z:
                self.undo()
                return
            if key == Qt.Key_C:
                self._on_action("copy")
                return
            if key == Qt.Key_S:
                self._on_action("save")
                return
            if key == Qt.Key_P:
                self._on_action("print")
                return
            if key == Qt.Key_A:
                self.selection = QRect(self.rect())
                self._has_selection = True
                self._show_panels()
                self.update()
                return

        if key in (Qt.Key_Return, Qt.Key_Enter) and self._editor is None:
            self._on_action("copy")
            return

        super().keyPressEvent(e)

    # ------------------------------------------------------------------ #
    #  Действия
    # ------------------------------------------------------------------ #
    def result_pixmap(self):
        """Готовый снимок выделенной области вместе с аннотациями."""
        self._commit_text()
        sel = self._sel_norm().intersected(self.rect())
        if sel.width() < 1 or sel.height() < 1:
            return None
        pm = self._shot.copy(sel)
        if self.shapes:
            p = QPainter(pm)
            try:
                p.setRenderHint(QPainter.Antialiasing, True)
                p.translate(-sel.topLeft())
                shapes_mod.draw_all(p, self.shapes, QRectF(sel))
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
