"""
Перечисление видимых окон — для подсветки окна под курсором.

Список снимается ОДИН раз, до показа оверлея: как только оверлей появится, он
сам станет верхним окном, и WindowFromPoint возвращал бы только его. Экран на
это время уже «заморожен» снимком, так что устаревать списку негде.

EnumWindows обходит окна в Z-порядке сверху вниз, поэтому окно под курсором —
первое подходящее, чей прямоугольник накрывает точку.
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QRect

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Настоящие границы окна: GetWindowRect у окон с Aero-рамкой прихватывает
# невидимые поля по 7 px с каждой стороны, и подсветка выглядела бы съехавшей.
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
# «Спрятанные» окна: свёрнутые UWP-приложения остаются видимыми для WinAPI, но
# на экране их нет.
_DWMWA_CLOAKED = 14

_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080

# Фон рабочего стола: окно во весь экран, подсвечивать его бессмысленно.
_SKIP_CLASSES = {"Progman", "WorkerW"}

# Минимальная сторона: окна-невидимки в 1 px только мешают.
_MIN_SIDE = 24


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _is_cloaked(hwnd):
    value = ctypes.c_int(0)
    res = _dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), ctypes.c_uint(_DWMWA_CLOAKED),
        ctypes.byref(value), ctypes.sizeof(value))
    return res == 0 and value.value != 0


def outer_rect(hwnd):
    """Прямоугольник окна вместе с невидимыми полями Aero — в таком размере
    PrintWindow рисует окно, и по нему считается смещение видимой части."""
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    return QRect(rect.left, rect.top,
                 rect.right - rect.left, rect.bottom - rect.top)


def frame_rect(hwnd):
    """Границы окна как их видит пользователь (без невидимых полей)."""
    return _frame_rect(hwnd)


def _frame_rect(hwnd):
    """Границы окна как их видит пользователь. None — окно нам не подходит."""
    rect = wintypes.RECT()
    res = _dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), ctypes.c_uint(_DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect), ctypes.sizeof(rect))
    if res != 0:
        # Windows без композитора (или окно без DWM-рамки) — берём как есть.
        if not _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width < _MIN_SIDE or height < _MIN_SIDE:
        return None
    return QRect(rect.left, rect.top, width, height)


def list_windows(clip=None):
    """[(hwnd, QRect)] видимых окон верхнего уровня, сверху вниз по Z.

    clip — прямоугольник виртуального экрана: окна обрезаются по нему, чтобы
    подсветка не уходила за пределы снимка."""
    own_pid = ctypes.windll.kernel32.GetCurrentProcessId()
    found = []

    def visit(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
            return True
        if _class_name(hwnd) in _SKIP_CLASSES:
            return True

        # Свои окна пропускаем: настройки прячутся перед съёмкой, но Qt делает
        # это не мгновенно, и окно ещё числилось бы видимым.
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:
            return True

        ex_style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        if ex_style & _WS_EX_TOOLWINDOW:
            return True
        if _is_cloaked(hwnd):
            return True

        rect = _frame_rect(hwnd)
        if rect is None:
            return True
        if clip is not None:
            rect = rect.intersected(clip)
            if rect.width() < _MIN_SIDE or rect.height() < _MIN_SIDE:
                return True
        found.append((int(hwnd), rect))
        return True

    try:
        _user32.EnumWindows(_WNDENUMPROC(visit), 0)
    except Exception:
        return []
    return found


def window_at(point, windows):
    """Верхнее окно под точкой или None. windows — результат list_windows()."""
    for _hwnd, rect in windows:
        if rect.contains(point):
            return rect
    return None
