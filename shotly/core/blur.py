"""
Размытие участков снимка: пикселизация и мягкое размытие.

Оба эффекта делаются уменьшением и обратным увеличением картинки — быстро,
средствами самого Qt и без сторонних библиотек. Пикселизация уменьшает грубо
(NN-интерполяция сохраняет квадраты), мягкое размытие — сглаженно и в несколько
проходов, чтобы результат не выглядел как мыльная лесенка.

Готовые размытые копии складываются в кэш: их считают один раз на снимок, а
перерисовка при каждом движении мыши уже ничего не пересчитывает.
"""

from PySide6.QtCore import Qt

KINDS = ("pixel", "soft")

# Четыре градации силы. Число — во сколько раз ужимается картинка: чем больше,
# тем крупнее «пиксели» и сильнее размытие.
LEVELS = (1, 2, 3, 4)
_PIXEL_FACTORS = {1: 6, 2: 12, 3: 22, 4: 36}
_SOFT_FACTORS = {1: 4, 2: 8, 3: 14, 4: 22}

# Сколько раз повторяется цикл «уменьшить-увеличить» для мягкого размытия. Один
# проход оставляет заметные разводы, три — уже неотличимо от гауссова.
_SOFT_PASSES = 3


def _shrink(pixmap, factor, mode):
    width = max(1, pixmap.width() // factor)
    height = max(1, pixmap.height() // factor)
    small = pixmap.scaled(width, height, Qt.IgnoreAspectRatio, mode)
    return small.scaled(pixmap.size(), Qt.IgnoreAspectRatio, mode)


def pixelate(pixmap, level=2):
    """Квадраты: уменьшаем и растягиваем обратно без сглаживания."""
    return _shrink(pixmap, _PIXEL_FACTORS.get(level, 12), Qt.FastTransformation)


def soften(pixmap, level=2):
    """Мягкое размытие: несколько сглаженных проходов уменьшения-увеличения."""
    factor = _SOFT_FACTORS.get(level, 8)
    out = pixmap
    for _ in range(_SOFT_PASSES):
        out = _shrink(out, factor, Qt.SmoothTransformation)
    return out


def apply(pixmap, kind, level):
    return pixelate(pixmap, level) if kind == "pixel" else soften(pixmap, level)


class BlurCache:
    """Размытые копии снимка по (вид, сила).

    Фигуры размытия рисуются вырезками отсюда, поэтому и кисть, и рамка берут
    один и тот же результат, а перерисовка стоит копейки. Копия полного снимка
    занимает ~25 МБ на экран 4K — держим не больше пары штук.
    """

    _LIMIT = 2

    def __init__(self, source=None):
        self._source = source
        self._cache = {}

    def set_source(self, pixmap):
        self._source = pixmap
        self._cache.clear()

    def get(self, kind, level):
        """Размытая копия снимка или None, если снимка нет."""
        if self._source is None or self._source.isNull():
            return None
        key = (kind, int(level))
        hit = self._cache.get(key)
        if hit is None:
            if len(self._cache) >= self._LIMIT:
                # Пользователь редко перебирает больше двух вариантов подряд;
                # старые копии держать незачем — это десятки мегабайт.
                self._cache.clear()
            hit = apply(self._source, kind, int(level))
            self._cache[key] = hit
        return hit

    def clear(self):
        self._cache.clear()
