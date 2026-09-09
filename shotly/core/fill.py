"""
Заливка области цветом — «ведро».

Заливаем по слою аннотаций, а не по снимку экрана: границей считается всё
нарисованное — фигура, кривая карандаша, стрелки крест-накрест, — а сам кадр под
ними значения не имеет. Иначе ведро цеплялось бы за контрасты на скриншоте и
заливало случайные куски интерфейса.

Считаем на уменьшенной копии кадра: на 4K-экране полноразмерный обход — это
миллионы шагов и заметная пауза, а для маски заливки такая точность не нужна,
край всё равно сглаживается при обратном увеличении. Уменьшение заодно
закрывает щели в один-два пикселя — незамкнутый от руки контур чаще всего
именно такой.

Если залилось почти всё выделение, значит контур дырявый и краска утекла
наружу: такую заливку не отдаём — лучше ничего, чем закрашенный экран.
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

# Во сколько раз ужимаем кадр перед обходом.
SCALE = 3

# Допуск по цвету: сумма расхождений по каналам, 0..765.
TOLERANCE = 60

# Доля выделения, после которой считаем, что краска утекла.
LEAK_SHARE = 0.85

# Меньше этого заливать нечего — скорее всего попали в саму линию.
MIN_PIXELS = 12


# Ниже этой прозрачности пиксель считается пустым — туда краска течёт.
ALPHA_EDGE = 40


def _is_empty(pixel):
    return (pixel >> 24 & 0xFF) < ALPHA_EDGE


def flood_mask(source, area, point, tolerance=TOLERANCE):
    """Маска заливки для точки point внутри area (координаты слоя аннотаций).

    source — прозрачный слой с фигурами. Возвращает (QImage-маска в размер
    area, доля залитого) или (None, доля), если заливать нечего или краска
    утекла за незамкнутый контур.
    """
    del tolerance                       # границы теперь определяет прозрачность
    if area.isEmpty() or not area.contains(point):
        return None, 0.0

    small_size = QSize(max(1, area.width() // SCALE), max(1, area.height() // SCALE))
    small = source.copy(area).scaled(small_size, Qt.IgnoreAspectRatio,
                                     Qt.SmoothTransformation)
    image = small.toImage().convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()

    start_x = min(width - 1, max(0, (point.x() - area.left()) * width // area.width()))
    start_y = min(height - 1, max(0, (point.y() - area.top()) * height // area.height()))

    # Пиксели читаем построчно из сырого буфера: обращаться к image.pixel()
    # по одному в Python втрое дороже.
    rows = []
    for y in range(height):
        line = image.constScanLine(y)
        rows.append(memoryview(line).cast("I")[:width])

    if not _is_empty(rows[start_y][start_x]):
        return None, 0.0                # ткнули в саму линию — заливать нечего
    visited = bytearray(width * height)
    stack = [(start_x, start_y)]
    visited[start_y * width + start_x] = 1
    filled = []

    while stack:
        x, y = stack.pop()
        filled.append((x, y))
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            index = ny * width + nx
            if visited[index]:
                continue
            if not _is_empty(rows[ny][nx]):
                continue                # упёрлись в нарисованное — это граница
            visited[index] = 1
            stack.append((nx, ny))

    share = len(filled) / float(width * height)
    if len(filled) < MIN_PIXELS or share > LEAK_SHARE:
        return None, share

    mask = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    mask.fill(Qt.transparent)
    white = QColor(255, 255, 255).rgba()
    for x, y in filled:
        mask.setPixel(x, y, white)

    # Обратно в полный размер: сглаживание убирает лесенку от уменьшенной сетки.
    return mask.scaled(area.size(), Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation), share


def colorize(mask, color):
    """Красит маску в цвет, сохраняя её прозрачность."""
    pixmap = QPixmap(mask.size())
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    try:
        p.drawImage(0, 0, mask)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(QRect(0, 0, mask.width(), mask.height()), QColor(color))
    finally:
        p.end()
    return pixmap
