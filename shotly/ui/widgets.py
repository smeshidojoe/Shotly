"""
Общие элементы окон: безрамочное окно с заголовком, вкладки-сегменты и поле
захвата горячей клавиши.
"""

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QLineEdit, QWidget

from ..core.hotkey import normalize, pretty
from ..core.i18n import tr
from . import icons, theme


# ---------------------------------------------------------------------- #
#  Безрамочное окно
# ---------------------------------------------------------------------- #
class Window(QWidget):
    """Окно со своей полосой заголовка: системная рамка Windows не умеет в нашу
    палитру, а половина окна — это как раз заголовок с вкладками."""

    # Окна создаются заново при каждом открытии, поэтому владельцу нужно знать,
    # когда отпустить ссылку (destroyed без WA_DeleteOnClose не приходит).
    closed = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(title)
        self._title = title
        self._drag = None
        self._radius = theme.s(12)
        self.title_h = theme.s(38)

        self._title_font = QFont("Segoe UI")
        self._title_font.setPixelSize(theme.s(13))

        self._close = _CloseButton(self)
        self._close.clicked.connect(self.close)
        self.setStyleSheet(theme.stylesheet())

    def set_title(self, title):
        """Смена языка на лету: заголовок перерисовывается, окно не пересоздаётся."""
        self._title = title
        self.setWindowTitle(title)
        self.update()

    def resizeEvent(self, e):
        m = theme.s(6)
        self._close.move(self.width() - self._close.width() - m,
                         (self.title_h - self._close.height()) // 2)
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.color("border"), 1))
        p.setBrush(theme.color("bg"))
        p.drawRoundedRect(r, self._radius, self._radius)

        p.setFont(self._title_font)
        p.setPen(QPen(theme.color("text")))
        p.drawText(QRect(theme.s(14), 0, self.width() - theme.s(60), self.title_h),
                   Qt.AlignLeft | Qt.AlignVCenter, self._title)

        # Тонкая линия под заголовком: отделяет шапку от содержимого.
        p.setPen(QPen(theme.color("border"), 1))
        p.drawLine(theme.s(1), self.title_h, self.width() - theme.s(1), self.title_h)
        p.end()

    # Окно таскается за шапку — системного заголовка, за который это делают
    # обычно, у нас нет.
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() <= self.title_h:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)

    def center_on_cursor_screen(self):
        from PySide6.QtGui import QCursor, QGuiApplication
        screen = QGuiApplication.screenAt(QCursor.pos()) or \
                 QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  area.center().y() - self.height() // 2)


class _CloseButton(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        side = theme.s(26)
        self.setFixedSize(side, side)
        self._hover = False
        self.setCursor(Qt.ArrowCursor)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("danger"))
            p.drawRoundedRect(QRectF(self.rect()), theme.s(6), theme.s(6))
        side = theme.s(12)
        col = "#ffffff" if self._hover else theme.PALETTE["text_dim"]
        p.drawPixmap(int((self.width() - side) / 2), int((self.height() - side) / 2),
                     icons.pixmap("close", side, col))
        p.end()


# ---------------------------------------------------------------------- #
#  Вкладки
# ---------------------------------------------------------------------- #
class TabBar(QWidget):
    """Сегментированный переключатель: подложка-«пилюля» едет под активный пункт."""

    changed = Signal(int)

    def __init__(self, titles, parent=None):
        super().__init__(parent)
        self._titles = list(titles)
        self._index = 0
        self._hover = -1
        self._font = QFont("Segoe UI")
        self._font.setPixelSize(theme.s(12))
        self._pad = theme.s(4)
        fm = QFontMetrics(self._font)
        self._cell = max(fm.horizontalAdvance(t) for t in self._titles) + theme.s(26)
        self.setFixedHeight(fm.height() + theme.s(14))
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

    def sizeHint(self):
        return QSize(self._cell * len(self._titles) + self._pad * 2, self.height())

    def index(self):
        return self._index

    def set_titles(self, titles):
        """Новые подписи вкладок (смена языка). Ширина ячейки пересчитывается:
        английские слова короче русских, и «пилюля» иначе не совпала бы с текстом."""
        self._titles = list(titles)
        fm = QFontMetrics(self._font)
        self._cell = max(fm.horizontalAdvance(t) for t in self._titles) + theme.s(26)
        self.updateGeometry()
        self.update()

    def set_index(self, i):
        i = max(0, min(int(i), len(self._titles) - 1))
        if i != self._index:
            self._index = i
            self.update()
            self.changed.emit(i)

    def _cell_rect(self, i):
        w = (self.width() - self._pad * 2) / len(self._titles)
        return QRectF(self._pad + i * w, self._pad, w,
                      self.height() - self._pad * 2)

    def mouseMoveEvent(self, e):
        pos = e.position()
        hit = -1
        for i in range(len(self._titles)):
            if self._cell_rect(i).contains(pos):
                hit = i
                break
        if hit != self._hover:
            self._hover = hit
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        for i in range(len(self._titles)):
            if self._cell_rect(i).contains(e.position()):
                self.set_index(i)
                return

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("field"))
        p.drawRoundedRect(r, theme.s(9), theme.s(9))

        sel = self._cell_rect(self._index)
        p.setBrush(theme.color("accent"))
        p.drawRoundedRect(sel, theme.s(7), theme.s(7))

        p.setFont(self._font)
        for i, title in enumerate(self._titles):
            if i == self._index:
                p.setPen(QPen(QColor(theme.PALETTE["on_accent"])))
            elif i == self._hover:
                p.setPen(QPen(theme.color("text")))
            else:
                p.setPen(QPen(theme.color("text_dim")))
            p.drawText(self._cell_rect(i), Qt.AlignCenter, title)
        p.end()


# ---------------------------------------------------------------------- #
#  Поле захвата горячей клавиши
# ---------------------------------------------------------------------- #
_QT_KEYS = {
    Qt.Key_Print: "print screen", Qt.Key_SysReq: "print screen",
    Qt.Key_Space: "space", Qt.Key_Tab: "tab", Qt.Key_Backspace: "backspace",
    Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
    Qt.Key_Insert: "insert", Qt.Key_Delete: "delete",
    Qt.Key_Home: "home", Qt.Key_End: "end",
    Qt.Key_PageUp: "page up", Qt.Key_PageDown: "page down",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left",
    Qt.Key_Right: "right", Qt.Key_Pause: "pause",
    Qt.Key_ScrollLock: "scroll lock", Qt.Key_Backslash: "\\",
    Qt.Key_BracketLeft: "[", Qt.Key_BracketRight: "]",
    Qt.Key_Semicolon: ";", Qt.Key_Apostrophe: "'", Qt.Key_Comma: ",",
    Qt.Key_Period: ".", Qt.Key_Slash: "/", Qt.Key_Minus: "-",
    Qt.Key_Equal: "=", Qt.Key_QuoteLeft: "`",
}

_MODS_ONLY = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
              Qt.Key_AltGr, Qt.Key_CapsLock, Qt.Key_NumLock}


def key_name(event):
    """Имя клавиши для библиотеки keyboard или '' — если это только модификатор."""
    key = event.key()
    if key in _MODS_ONLY:
        return ""
    if key in _QT_KEYS:
        return _QT_KEYS[key]
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return "f%d" % (key - Qt.Key_F1 + 1)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key)
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key).lower()
    # Нелатинская раскладка: буква приходит кириллицей, а keyboard ждёт код
    # клавиши. nativeVirtualKey — единственный надёжный источник.
    vk = event.nativeVirtualKey()
    if 0x30 <= vk <= 0x5A:
        return chr(vk).lower()
    return ""


class HotkeyEdit(QLineEdit):
    """Поле «нажмите сочетание»: показывает Ctrl + Prnt Scrn, хранит 'ctrl+print screen'."""

    combo_changed = Signal(str)

    def __init__(self, combo="", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self._combo = combo
        self._capturing = False
        self.setText(pretty(combo))
        self.setCursor(Qt.ArrowCursor)

    def combo(self):
        return self._combo

    def set_combo(self, combo):
        self._combo = combo or ""
        self.setText(pretty(self._combo))

    def focusInEvent(self, e):
        self._capturing = True
        self.setText(tr("Press a key combination"))
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._capturing = False
        self.setText(pretty(self._combo))
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        if not self._capturing:
            return
        if e.key() == Qt.Key_Escape:
            self.clearFocus()
            return
        name = key_name(e)
        if not name:
            return
        mods = set()
        m = e.modifiers()
        if m & Qt.ControlModifier:
            mods.add("ctrl")
        if m & Qt.ShiftModifier:
            mods.add("shift")
        if m & Qt.AltModifier:
            mods.add("alt")
        if m & Qt.MetaModifier:
            mods.add("win")
        combo = normalize(mods, name)
        self._combo = combo
        self.setText(pretty(combo))
        self.combo_changed.emit(combo)
        self.clearFocus()

    def keyReleaseEvent(self, e):
        pass
