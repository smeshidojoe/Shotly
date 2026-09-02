"""
Иконка в трее и её меню.

Меню своё, а не QMenu: системное меню Windows рисуется светлым и с чужими
отступами, а оно — единственное лицо программы между съёмками.
"""

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import (QCursor, QFont, QFontMetrics, QGuiApplication,
                           QPainter, QPen)
from PySide6.QtWidgets import QSystemTrayIcon, QWidget

from .core.constants import APP_NAME
from .core.i18n import tr
from .ui import icons, theme


class TrayMenu(QWidget):
    """Тёмное скруглённое меню: строка = иконка + подпись, подсветка под курсором."""

    def __init__(self, items):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

        self._items = list(items)          # [(icon, label, callback)]
        self._hover = -1
        self._font = QFont("Segoe UI")
        self._font.setPixelSize(theme.s(13))
        self._pad = theme.s(5)
        self._icon = theme.s(16)
        self._gap = theme.s(10)

        fm = QFontMetrics(self._font)
        self._row_h = fm.height() + theme.s(14)
        width = max(fm.horizontalAdvance(label) for _i, label, _c in self._items)
        self.resize(self._pad * 2 + theme.s(14) + self._icon + self._gap
                    + width + theme.s(16),
                    self._pad * 2 + self._row_h * len(self._items))

    # ------------------------------------------------------------------ #
    def popup_at(self, gpos):
        screen = QGuiApplication.screenAt(gpos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x, y = gpos.x(), gpos.y()
        # Трей внизу справа: меню почти всегда разворачивается вверх и влево.
        if y + self.height() > area.bottom():
            y = gpos.y() - self.height()
        if x + self.width() > area.right():
            x = gpos.x() - self.width()
        self.move(QPoint(max(area.left(), x), max(area.top(), y)))
        self.show()
        self.raise_()
        self.activateWindow()

    def _row_at(self, pos):
        if not (self._pad <= pos.y() < self.height() - self._pad):
            return -1
        i = int((pos.y() - self._pad) // self._row_h)
        return i if 0 <= i < len(self._items) else -1

    def mouseMoveEvent(self, e):
        hit = self._row_at(e.position().toPoint())
        if hit != self._hover:
            self._hover = hit
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        i = self._row_at(e.position().toPoint())
        self.close()
        if i >= 0:
            self._items[i][2]()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()

    # ------------------------------------------------------------------ #
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.color("border"), 1))
        p.setBrush(theme.color("panel"))
        p.drawRoundedRect(r, theme.s(10), theme.s(10))

        p.setFont(self._font)
        for i, (icon_name, label, _cb) in enumerate(self._items):
            top = self._pad + i * self._row_h
            row = QRectF(self._pad, top, self.width() - self._pad * 2, self._row_h)
            if i == self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(theme.color("accent"))
                p.drawRoundedRect(row.adjusted(1, 0, -1, 0), theme.s(7), theme.s(7))

            col = (theme.PALETTE["on_accent"] if i == self._hover
                   else theme.PALETTE["text"])
            x = row.left() + theme.s(10)
            p.drawPixmap(int(x), int(top + (self._row_h - self._icon) / 2),
                         icons.pixmap(icon_name, self._icon, col))
            p.setPen(QPen(theme.color("text") if i != self._hover
                          else theme.color("on_accent")))
            p.drawText(QRectF(x + self._icon + self._gap, top,
                              row.right() - x - self._icon - self._gap, self._row_h),
                       Qt.AlignLeft | Qt.AlignVCenter, label)
        p.end()


class Tray(QSystemTrayIcon):
    """Левый клик — снимок (как в Lightshot), правый — меню."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._menu = None
        self.setIcon(icons.app_icon())
        self.retranslate()
        self.activated.connect(self._on_activated)

    def retranslate(self):
        self.setToolTip("%s — %s" % (APP_NAME, tr("Take a screenshot")))

    def run(self):
        self.show()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._app.start_capture()
        elif reason == QSystemTrayIcon.Context:
            self.open_menu()

    def open_menu(self):
        if self._menu is not None:
            self._menu.close()
        items = [
            ("camera", tr("Take a screenshot"), self._app.start_capture),
            ("save", tr("Capture full screen"), self._app.capture_full_save),
            ("settings", tr("Settings..."), self._app.open_settings),
            ("info", tr("About..."), self._app.open_about),
            ("quit", tr("Quit"), self._app.quit),
        ]
        self._menu = TrayMenu(items)
        self._menu.popup_at(QCursor.pos())
