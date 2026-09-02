"""
Генератор картинок проекта:

    assets/app.ico          — иконка exe и трея (7 размеров)
    assets/icon.png         — иконка 1024x1024 для аватарки/страницы релиза
    assets/app.png          — она же 256x256, для README
    assets/cover.png        — обложка 1280x720 для карточки программы

Иконку рисует тот же код, что и запасную иконку в рантайме
(ui/icons.app_pixmap), поэтому файл и нарисованный вариант не разъезжаются.
Каждый размер ico рендерится отдельно, а не ужимается из 1024 — ужатая версия
на 16x16 превращалась в кашу.

    python tools/make_assets.py
"""

import io
import os
import sys

# Платформу НЕ переключаем в offscreen: там Qt не видит системные шрифты, и
# весь текст обложки уходит в «тофу»-квадраты. Окон скрипт всё равно не создаёт.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QLinearGradient,  # noqa: E402
                           QPainter, QPen, QPixmap, QRadialGradient)

ICO_SIZES = [256, 128, 64, 48, 32, 24, 16]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets")

COVER_W, COVER_H = 1280, 720
BG_TOP, BG_BOTTOM = "#1b1e24", "#131519"
ACCENT = "#4f8cff"
TEXT = "#f2f4f8"
TEXT_DIM = "#98a1ad"


# ---------------------------------------------------------------------- #
def _png_bytes(pixmap):
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()
    return bytes(buf.data())


def write_icons(app_pixmap):
    from PIL import Image

    frames = [Image.open(io.BytesIO(_png_bytes(app_pixmap(s)))).convert("RGBA")
              for s in ICO_SIZES]
    ico = os.path.join(OUT_DIR, "app.ico")
    frames[0].save(ico, format="ICO",
                   sizes=[(f.width, f.height) for f in frames],
                   append_images=frames[1:])

    app_pixmap(1024).save(os.path.join(OUT_DIR, "icon.png"), "PNG")
    app_pixmap(256).save(os.path.join(OUT_DIR, "app.png"), "PNG")
    return ico


# ---------------------------------------------------------------------- #
def _dashed_frame(p, rect):
    """Рамка выделения «бегущими муравьями» с белыми ручками — тот же приём, что
    в самом приложении: обложка должна читаться как скриншот-инструмент."""
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 160), 2))
    p.drawRect(rect)
    pen = QPen(QColor("#ffffff"), 2)
    pen.setStyle(Qt.CustomDashLine)
    pen.setDashPattern([6, 6])
    p.setPen(pen)
    p.drawRect(rect)

    side = 12
    p.setPen(QPen(QColor("#1a1a1a"), 1))
    p.setBrush(QColor("#ffffff"))
    for fx, fy in ((0, 0), (0.5, 0), (1, 0), (1, 0.5),
                   (1, 1), (0.5, 1), (0, 1), (0, 0.5)):
        cx = rect.left() + rect.width() * fx
        cy = rect.top() + rect.height() * fy
        p.drawRect(QRectF(cx - side / 2, cy - side / 2, side, side))


def _size_chip(p, rect, text):
    """Подпись размера над рамкой — как в оверлее программы."""
    font = QFont("Segoe UI")
    font.setPixelSize(20)
    p.setFont(font)
    fm = p.fontMetrics()
    w = fm.horizontalAdvance(text) + 24
    h = fm.height() + 12
    chip = QRectF(rect.left(), rect.top() - h - 12, w, h)
    p.setPen(QPen(QColor(0, 0, 0, 160), 1))
    p.setBrush(QColor("#24282e"))
    p.drawRoundedRect(chip, 8, 8)
    p.setPen(QPen(QColor(TEXT)))
    p.drawText(chip, Qt.AlignCenter, text)


def write_cover(app_pixmap):
    pm = QPixmap(COVER_W, COVER_H)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        grad = QLinearGradient(0, 0, 0, COVER_H)
        grad.setColorAt(0.0, QColor(BG_TOP))
        grad.setColorAt(1.0, QColor(BG_BOTTOM))
        p.fillRect(pm.rect(), grad)

        # Мягкое свечение за иконкой: без него центр композиции проваливается.
        glow = QRadialGradient(QPointF(COVER_W / 2, 300), 420)
        accent = QColor(ACCENT)
        accent.setAlpha(46)
        glow.setColorAt(0.0, accent)
        accent2 = QColor(ACCENT)
        accent2.setAlpha(0)
        glow.setColorAt(1.0, accent2)
        p.fillRect(pm.rect(), glow)

        frame = QRectF(150, 116, COVER_W - 300, COVER_H - 232)
        _dashed_frame(p, frame)
        _size_chip(p, frame, "%d x %d" % (COVER_W, COVER_H))

        icon = app_pixmap(1024).scaled(216, 216, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation)
        p.drawPixmap(int((COVER_W - icon.width()) / 2), 176, icon)

        title = QFont("Segoe UI")
        title.setPixelSize(104)
        title.setWeight(QFont.DemiBold)
        p.setFont(title)
        p.setPen(QPen(QColor(TEXT)))
        p.drawText(QRect(0, 396, COVER_W, 130), Qt.AlignHCenter | Qt.AlignTop,
                   "Shotly")

        sub = QFont("Segoe UI")
        sub.setPixelSize(28)
        p.setFont(sub)
        p.setPen(QPen(QColor(TEXT_DIM)))
        p.drawText(QRect(int(frame.left()), 534, int(frame.width()), 46),
                   Qt.AlignHCenter | Qt.AlignTop,
                   "Выделить область, порисовать, скопировать или сохранить")

        # Ряд инструментов — под рамкой, а не на ней: иначе иконки садятся прямо
        # на пунктир и читаются как его часть.
        from shotly.ui import icons as app_icons
        tools = ["pen", "line", "arrow", "rect", "marker", "text", "copy", "save"]
        side, gap = 32, 30
        total = len(tools) * side + (len(tools) - 1) * gap
        x = (COVER_W - total) / 2
        y = int(frame.bottom()) + 32
        for name in tools:
            p.drawPixmap(int(x), y, app_icons.pixmap(name, side, TEXT_DIM))
            x += side + gap
    finally:
        p.end()

    out = os.path.join(OUT_DIR, "cover.png")
    pm.save(out, "PNG")
    return out


# ---------------------------------------------------------------------- #
def main():
    QGuiApplication([])                 # нужен живой экземпляр для QPixmap
    from shotly.ui.icons import app_pixmap

    os.makedirs(OUT_DIR, exist_ok=True)
    print("written:", write_icons(app_pixmap))
    print("written:", os.path.join(OUT_DIR, "icon.png"))
    print("written:", write_cover(app_pixmap))


if __name__ == "__main__":
    main()
