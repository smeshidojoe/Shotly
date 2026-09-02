"""
Блокирующий оверлей окна: затемнение, заголовок и полоса прогресса.

Нужен там, где прервать операцию нельзя — при загрузке обновления. Закрытое
посреди скачивания окно оборвало бы загрузку, а сигналы воркера прилетели бы в
уже удалённый объект. Поэтому на время операции окно накрывается этим виджетом:
он глотает клики и вместе с Window.set_locked() запирает закрытие.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class BusyOverlay(QWidget):
    def __init__(self, parent, title=""):
        super().__init__(parent)
        self._title = title
        self._progress = None            # None — прогресс неизвестен
        self._radius = theme.s(12)

        self._font = QFont("Segoe UI")
        self._font.setPixelSize(theme.s(13))
        self._small = QFont("Segoe UI")
        self._small.setPixelSize(theme.s(11))

        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.ArrowCursor)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

    # ------------------------------------------------------------------ #
    def eventFilter(self, obj, event):
        # Окно фиксированного размера, но подстраховка дешёвая: оверлей всегда
        # накрывает его целиком, иначе в щель можно было бы кликнуть.
        if obj is self.parentWidget() and event.type() == event.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return False

    def set_title(self, text):
        self._title = text
        self.update()

    def set_progress(self, frac):
        """frac 0..1 или None — «идёт, доля неизвестна»."""
        self._progress = None if frac is None else max(0.0, min(1.0, float(frac)))
        self.update()

    # Клики и клавиши до окна под оверлеем не доходят.
    def mousePressEvent(self, e):
        e.accept()

    def mouseReleaseEvent(self, e):
        e.accept()

    def keyPressEvent(self, e):
        e.accept()

    # ------------------------------------------------------------------ #
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Затемнение по форме окна: окно скруглённое, прямоугольная заливка
        # вылезала бы за его углы.
        dim = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(dim, self._radius, self._radius)

        card_w, card_h = theme.s(300), theme.s(104)
        card = QRectF((self.width() - card_w) / 2, (self.height() - card_h) / 2,
                      card_w, card_h)
        p.setPen(QPen(theme.color("border"), 1))
        p.setBrush(theme.color("panel"))
        p.drawRoundedRect(card, theme.s(14), theme.s(14))

        p.setFont(self._font)
        p.setPen(QPen(theme.color("text")))
        p.drawText(QRectF(card.left(), card.top() + theme.s(20), card_w,
                          theme.s(20)), Qt.AlignCenter, self._title)

        track = QRectF(card.left() + theme.s(24),
                       card.top() + theme.s(56),
                       card_w - theme.s(48), theme.s(6))
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("field"))
        p.drawRoundedRect(track, theme.s(3), theme.s(3))

        if self._progress is not None:
            done = QRectF(track)
            done.setWidth(track.width() * self._progress)
            p.setBrush(theme.color("accent"))
            p.drawRoundedRect(done, theme.s(3), theme.s(3))

            p.setFont(self._small)
            p.setPen(QPen(theme.color("text_dim")))
            p.drawText(QRectF(card.left(), track.bottom() + theme.s(6), card_w,
                              theme.s(16)), Qt.AlignCenter,
                       "%d%%" % int(self._progress * 100))
        p.end()

    def close_overlay(self):
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        self.deleteLater()
