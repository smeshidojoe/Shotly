"""
Панели оверлея: инструменты рисования (вертикальная, справа от выделения) и
действия (горизонтальная, под выделением).

Обе — обычные дочерние виджеты оверлея, а не отдельные окна: так они гарантированно
поверх затемнения, не мигают на переключении фокуса и позиционируются в тех же
координатах, что и рамка выделения.
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core.i18n import tr
from . import icons, theme


class _Button(QWidget):
    """Квадратная кнопка панели: иконка, подсветка под курсором, режим «нажата»."""

    clicked = Signal(str)

    def __init__(self, name, tooltip, parent=None, checkable=False):
        super().__init__(parent)
        self.name = name
        self.checkable = checkable
        self.checked = False
        self._hover = False
        self._side = theme.s(28)
        self._icon = theme.s(18)
        self.setFixedSize(self._side, self._side)
        self.setCursor(Qt.ArrowCursor)
        self.setMouseTracking(True)
        self.setToolTip(tooltip)

    def sizeHint(self):
        return QSize(self._side, self._side)

    def set_checked(self, on):
        if self.checked != on:
            self.checked = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.name)
        e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.s(6)
        if self.checked:
            # Выбранный инструмент подсвечиваем белым, а не фирменным синим:
            # панель стоит поверх чужого кадра, и цветное пятно на нём мешает.
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.OVERLAY["active"]))
            p.drawRoundedRect(r, radius, radius)
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("field_hi"))
            p.drawRoundedRect(r, radius, radius)

        if self.checked:
            col = theme.OVERLAY["on_active"]
        else:
            col = theme.PALETTE["text"] if self.isEnabled() else theme.PALETTE["text_dim"]
        pm = icons.pixmap(self.name, self._icon, col)
        p.drawPixmap(int((self.width() - self._icon) / 2),
                     int((self.height() - self._icon) / 2), pm)
        p.end()


class _ColorButton(_Button):
    """Кнопка выбора цвета: вместо иконки — образец текущего цвета."""

    def __init__(self, color, parent=None):
        super().__init__("color", tr("Color"), parent)
        self._color = QColor(color)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.s(6)
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("field_hi"))
            p.drawRoundedRect(r, radius, radius)
        swatch = r.adjusted(theme.s(6), theme.s(6), -theme.s(6), -theme.s(6))
        p.setBrush(self._color)
        # Тёмная обводка: без неё чёрный образец сливался бы с панелью.
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.drawRoundedRect(swatch, theme.s(3), theme.s(3))
        p.end()


class _Panel(QWidget):
    """Скруглённая подложка с рядом кнопок."""

    def __init__(self, parent, vertical):
        super().__init__(parent)
        self._vertical = vertical
        self._pad = theme.s(4)
        self._gap = theme.s(2)
        self._buttons = []
        self.setCursor(Qt.ArrowCursor)

    def _add(self, btn):
        btn.setParent(self)
        self._buttons.append(btn)
        return btn

    def relayout(self):
        """Раскладывает кнопки в линию и подгоняет размер панели под них."""
        x = y = self._pad
        side = 0
        for b in self._buttons:
            b.move(x, y)
            side = b.width()
            if self._vertical:
                y += b.height() + self._gap
            else:
                x += b.width() + self._gap
        n = len(self._buttons)
        if not n:
            self.resize(self._pad * 2, self._pad * 2)
            return
        run = side * n + self._gap * (n - 1) + self._pad * 2
        cross = side + self._pad * 2
        self.resize(cross if self._vertical else run,
                    run if self._vertical else cross)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.s(9)
        p.setPen(QPen(theme.color("border"), 1))
        bg = theme.color("panel")
        bg.setAlpha(242)                 # чуть просвечивает — панель не «висит доской»
        p.setBrush(bg)
        p.drawRoundedRect(r, radius, radius)
        p.end()


class ToolPanel(_Panel):
    """Карандаш, линия, стрелка, прямоугольник, маркер, текст, цвет, отмена."""

    tool_picked = Signal(str)
    color_clicked = Signal()
    undo_clicked = Signal()

    def __init__(self, parent, color):
        super().__init__(parent, vertical=True)
        self._tools = {}
        for name, tip in (("pen", tr("Pen")), ("line", tr("Line")),
                          ("arrow", tr("Arrow")), ("rect", tr("Rectangle")),
                          ("marker", tr("Marker")), ("text", tr("Text"))):
            b = self._add(_Button(name, tip, self, checkable=True))
            b.clicked.connect(self._on_tool)
            self._tools[name] = b

        self.color_btn = self._add(_ColorButton(color, self))
        self.color_btn.clicked.connect(lambda _n: self.color_clicked.emit())

        self.undo_btn = self._add(_Button("undo", tr("Undo") + "  (Ctrl+Z)", self))
        self.undo_btn.clicked.connect(lambda _n: self.undo_clicked.emit())
        self.relayout()

    def _on_tool(self, name):
        # Повторный клик по активному инструменту выключает рисование — так
        # можно вернуться к перетаскиванию рамки, не отменяя снимок.
        self.set_tool(None if self._tools[name].checked else name)
        self.tool_picked.emit("" if not self.current() else self.current())

    def set_tool(self, name):
        for key, btn in self._tools.items():
            btn.set_checked(key == name)

    def current(self):
        for key, btn in self._tools.items():
            if btn.checked:
                return key
        return ""

    def set_color(self, color):
        self.color_btn.set_color(color)

    def set_undo_enabled(self, on):
        self.undo_btn.setEnabled(on)
        self.undo_btn.update()


class ActionPanel(_Panel):
    """Печать, копирование, сохранение, отмена съёмки."""

    triggered = Signal(str)

    def __init__(self, parent):
        super().__init__(parent, vertical=False)
        for name, tip in (("print", tr("Print") + "  (Ctrl+P)"),
                          ("copy", tr("Copy") + "  (Ctrl+C)"),
                          ("save", tr("Save") + "  (Ctrl+S)"),
                          ("close", tr("Cancel capture") + "  (Esc)")):
            b = self._add(_Button(name, tip, self))
            b.clicked.connect(self.triggered.emit)
        self.relayout()
