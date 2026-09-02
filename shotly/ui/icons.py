"""
Иконки рисуются кодом, а не берутся из файлов.

Их полтора десятка, все — простые штриховые глифы: держать ради них папку с PNG
под каждый масштаб (а масштабов у нас столько же, сколько DPI у мониторов) дороже,
чем нарисовать путями. Каждая иконка живёт в квадрате 24x24 и масштабируется в
запрошенный размер.
"""

import os
from math import cos, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)

from ..core.constants import APP_DIR, APP_ICO

_BOX = 24.0
_cache = {}


# ------------------------------------------------------------------ #
def pixmap(name, size, color="#e6e9ee"):
    """QPixmap с иконкой name стороной size, обведённой цветом color."""
    key = (name, int(size), str(color))
    hit = _cache.get(key)
    if hit is not None:
        return hit

    pm = QPixmap(int(size), int(size))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(size / _BOX, size / _BOX)
        col = QColor(color)
        pen = QPen(col, 1.9)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        painter = _PAINTERS.get(name)
        if painter:
            painter(p, col)
    finally:
        p.end()

    _cache[key] = pm
    return pm


def icon(name, size, color="#e6e9ee"):
    return QIcon(pixmap(name, size, color))


def clear_cache():
    _cache.clear()


# ------------------------------------------------------------------ #
#  Инструменты рисования
# ------------------------------------------------------------------ #
def _pen(p, col):
    # Карандаш: корпус по диагонали + грифель.
    body = QPolygonF([QPointF(5, 19), QPointF(6.6, 14.6), QPointF(16.4, 4.8),
                      QPointF(19.2, 7.6), QPointF(9.4, 17.4)])
    p.drawPolygon(body)
    p.drawLine(QPointF(6.6, 14.6), QPointF(9.4, 17.4))


def _line(p, col):
    p.drawLine(QPointF(5, 19), QPointF(19, 5))


def _arrow(p, col):
    # Крылья строятся поворотом обратного вектора на ±25°, иначе наконечник
    # получается косым: раньше он был нарисован «на глаз» и заваливался влево.
    tip, tail = QPointF(18.5, 5.5), QPointF(5.5, 18.5)
    p.drawLine(tail, tip)
    dx, dy = tail.x() - tip.x(), tail.y() - tip.y()
    length = (dx * dx + dy * dy) ** 0.5
    dx, dy = dx / length, dy / length
    wing = 7.0
    for angle in (radians(25), radians(-25)):
        c, s_ = cos(angle), sin(angle)
        p.drawLine(tip, QPointF(tip.x() + wing * (dx * c - dy * s_),
                                tip.y() + wing * (dx * s_ + dy * c)))


def _rect(p, col):
    p.drawRoundedRect(QRectF(4.5, 6.5, 15, 11), 1.5, 1.5)


def _marker(p, col):
    # Маркер: наклонный корпус, широкий скос пера и след под ним.
    body = QPolygonF([QPointF(8, 15), QPointF(14.5, 4.5), QPointF(19, 7.5),
                      QPointF(12.5, 18), QPointF(8.5, 18)])
    p.drawPolygon(body)
    p.drawLine(QPointF(8, 15), QPointF(12.5, 18))
    thick = QPen(col, 2.6)
    thick.setCapStyle(Qt.RoundCap)
    p.setPen(thick)
    p.drawLine(QPointF(5, 20.4), QPointF(15, 20.4))


def _text(p, col):
    p.drawLine(QPointF(6, 6), QPointF(18, 6))
    p.drawLine(QPointF(12, 6), QPointF(12, 18.5))
    p.drawLine(QPointF(9, 18.5), QPointF(15, 18.5))


def _undo(p, col):
    path = QPainterPath(QPointF(6, 11))
    path.arcTo(QRectF(6, 6.5, 13, 11), 170, -230)
    p.drawPath(path)
    p.drawLine(QPointF(6, 11), QPointF(5.4, 6.2))
    p.drawLine(QPointF(6, 11), QPointF(10.6, 10.2))


# ------------------------------------------------------------------ #
#  Действия
# ------------------------------------------------------------------ #
def _print(p, col):
    p.drawLine(QPointF(7, 9), QPointF(7, 4.5))
    p.drawLine(QPointF(7, 4.5), QPointF(17, 4.5))
    p.drawLine(QPointF(17, 4.5), QPointF(17, 9))
    p.drawRoundedRect(QRectF(4, 9, 16, 7), 1.5, 1.5)
    p.fillRect(QRectF(7.5, 13.5, 9, 6), col)


def _copy(p, col):
    p.drawRoundedRect(QRectF(4.5, 4.5, 11, 11), 1.6, 1.6)
    p.drawRoundedRect(QRectF(8.5, 8.5, 11, 11), 1.6, 1.6)


def _save(p, col):
    p.drawLine(QPointF(12, 3.5), QPointF(12, 14))
    p.drawLine(QPointF(7.5, 9.8), QPointF(12, 14.3))
    p.drawLine(QPointF(16.5, 9.8), QPointF(12, 14.3))
    p.drawLine(QPointF(4.5, 18), QPointF(19.5, 18))


def _close(p, col):
    p.drawLine(QPointF(6, 6), QPointF(18, 18))
    p.drawLine(QPointF(18, 6), QPointF(6, 18))


def _check(p, col):
    pen = QPen(col, 2.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(5.5, 12.5), QPointF(10, 17))
    p.drawLine(QPointF(10, 17), QPointF(18.5, 7.5))


def _settings(p, col):
    p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
    for i in range(8):
        a = radians(i * 45)
        p.drawLine(QPointF(12 + 6.0 * cos(a), 12 + 6.0 * sin(a)),
                   QPointF(12 + 8.4 * cos(a), 12 + 8.4 * sin(a)))


def _camera(p, col):
    p.drawRoundedRect(QRectF(3.5, 7, 17, 13), 2.5, 2.5)
    p.drawLine(QPointF(8.5, 7), QPointF(10, 4.5))
    p.drawLine(QPointF(10, 4.5), QPointF(14, 4.5))
    p.drawLine(QPointF(14, 4.5), QPointF(15.5, 7))
    p.drawEllipse(QPointF(12, 13.5), 3.4, 3.4)


def _info(p, col):
    p.drawEllipse(QPointF(12, 12), 8.2, 8.2)
    p.drawLine(QPointF(12, 10.5), QPointF(12, 16.5))
    p.drawPoint(QPointF(12, 7.6))
    p.drawEllipse(QPointF(12, 7.6), 0.5, 0.5)


def _quit(p, col):
    path = QPainterPath(QPointF(15.6, 6.4))
    path.arcTo(QRectF(4.6, 4.6, 14.8, 14.8), 55, 250)
    p.drawPath(path)
    p.drawLine(QPointF(12, 3.4), QPointF(12, 11.4))


_PAINTERS = {
    "pen": _pen, "line": _line, "arrow": _arrow, "rect": _rect,
    "marker": _marker, "text": _text, "undo": _undo,
    "print": _print, "copy": _copy, "save": _save, "close": _close,
    "check": _check, "settings": _settings, "camera": _camera,
    "info": _info, "quit": _quit,
}


# ------------------------------------------------------------------ #
#  Галочка для QSS и иконка приложения
# ------------------------------------------------------------------ #
_check_path = None


def check_mark_path(size=16, color="#ffffff"):
    """QSS умеет только url(...) — рисуем галочку один раз в файл и отдаём путь
    в том виде, в каком его понимает Qt (прямые слэши)."""
    global _check_path
    if _check_path and os.path.isfile(_check_path):
        return _check_path
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        path = os.path.join(APP_DIR, "check-%d.png" % size)
        if not os.path.isfile(path):
            pixmap("check", size, color).save(path, "PNG")
        _check_path = path.replace("\\", "/")
        return _check_path
    except OSError:
        return ""


def app_icon():
    """Иконка приложения: файл из assets, а если его нет — нарисованная."""
    if os.path.isfile(APP_ICO):
        ic = QIcon(APP_ICO)
        if not ic.isNull():
            return ic
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(app_pixmap(size))
    return ic


# Оптические размеры иконки. Один рисунок на все случаи не годится: на 16 px
# (иконка в трее и в заголовке окна) тонкие уголки и крест слипаются в кляксу.
# Чем меньше размер, тем толще штрих, короче уголки и мельче прицел; на самых
# мелких прицел вырождается в точку — линии там всё равно не читаются.
#   (порог, отступ фона, радиус фона, толщина штриха, длина уголка, полукрест)
_APP_ICON_STEPS = (
    (20,  4.0, 46.0, 30.0, 40.0, 0.0),
    (40,  6.0, 50.0, 24.0, 46.0, 30.0),
    (None, 8.0, 54.0, 15.0, 44.0, 24.0),      # None — всё, что крупнее
)

APP_ICON_BG     = "#22262d"
APP_ICON_FRAME  = "#e6e9ee"
APP_ICON_ACCENT = "#4f8cff"


def app_pixmap(size=256):
    """Иконка приложения: рамка выделения с прицелом на тёмном скруглённом поле.

    Рисуется кодом, а не берётся из файла: тот же вызов делает и app.ico
    (tools/make_assets.py), и запасной вариант в рантайме, поэтому файл и
    нарисованная иконка не могут разойтись.
    """
    pad, radius, stroke, arm, cross = next(
        step[1:] for step in _APP_ICON_STEPS
        if step[0] is None or size <= step[0])

    pm = QPixmap(int(size), int(size))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(size / 256.0, size / 256.0)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(APP_ICON_BG))
        p.drawRoundedRect(QRectF(pad, pad, 256 - pad * 2, 256 - pad * 2),
                          radius, radius)

        # Уголки рамки выделения.
        pen = QPen(QColor(APP_ICON_FRAME), stroke)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        inset = pad + 52 - stroke / 2
        r = QRectF(inset, inset, 256 - inset * 2, 256 - inset * 2)
        for cx, cy, dx, dy in ((r.left(), r.top(), 1, 1),
                               (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1),
                               (r.right(), r.bottom(), -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + arm * dx, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + arm * dy))

        # Прицел по центру — акцентом.
        pen = QPen(QColor(APP_ICON_ACCENT), stroke)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        if cross <= 0:
            p.drawPoint(QPointF(128, 128))       # точка вместо креста
        else:
            p.drawLine(QPointF(128, 128 - cross), QPointF(128, 128 + cross))
            p.drawLine(QPointF(128 - cross, 128), QPointF(128 + cross, 128))
    finally:
        p.end()
    return pm
