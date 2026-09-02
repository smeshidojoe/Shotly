"""
Захват экрана.

Основной путь — Win32 BitBlt по всему виртуальному рабочему столу: он берёт
физические пиксели (процесс объявлен per-monitor DPI aware) и позволяет дорисовать
курсор прямо в кадр через DrawIconEx. Запасной путь — QScreen.grabWindow(0) по
каждому экрану, на случай отсутствия pywin32.

Важно: приложение запускается с QT_ENABLE_HIGHDPI_SCALING=0 (см. main.py), поэтому
логические координаты Qt равны физическим пикселям. Оверлей ложится на экран
пиксель в пиксель, и снимок не приходится ни растягивать, ни делить на dpr.
"""

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QImage, QPixmap, QPainter

_SM = {"x": 76, "y": 77, "w": 78, "h": 79}     # SM_*VIRTUALSCREEN
_CAPTUREBLT = 0x40000000                        # берёт и слоистые окна
_DI_NORMAL = 0x0003


def virtual_rect():
    """Прямоугольник всего рабочего стола (объединение мониторов), в пикселях."""
    r = QRect()
    for s in QGuiApplication.screens():
        r = r.united(s.geometry())
    if r.isEmpty():
        r = QRect(0, 0, 1920, 1080)
    return r


# ---------------------------------------------------------------------- #
def grab(with_cursor=False):
    """QPixmap всего рабочего стола. None — если снять не удалось."""
    img = _grab_win32(with_cursor)
    if img is not None:
        return img
    return _grab_qt()


def _grab_win32(with_cursor):
    try:
        import win32api
        import win32con
        import win32gui
        import win32ui
    except Exception:
        return None

    x = win32api.GetSystemMetrics(_SM["x"])
    y = win32api.GetSystemMetrics(_SM["y"])
    w = win32api.GetSystemMetrics(_SM["w"])
    h = win32api.GetSystemMetrics(_SM["h"])
    if w <= 0 or h <= 0:
        return None

    desktop = win32gui.GetDesktopWindow()
    src_hdc = win32gui.GetWindowDC(desktop)
    src_dc = mem_dc = bmp = None
    try:
        src_dc = win32ui.CreateDCFromHandle(src_hdc)
        mem_dc = src_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(src_dc, w, h)
        mem_dc.SelectObject(bmp)
        mem_dc.BitBlt((0, 0), (w, h), src_dc, (x, y),
                      win32con.SRCCOPY | _CAPTUREBLT)

        if with_cursor:
            _draw_cursor(win32gui, mem_dc.GetSafeHdc(), x, y)

        bits = bmp.GetBitmapBits(True)
        # 32 бита на пиксель, порядок байт BGRA — это и есть QImage.Format_RGB32
        # на little-endian, так что перекладывать каналы не нужно.
        img = QImage(bits, w, h, QImage.Format_RGB32).copy()
        return QPixmap.fromImage(img)
    except Exception:
        return None
    finally:
        try:
            if bmp is not None:
                win32gui.DeleteObject(bmp.GetHandle())
        except Exception:
            pass
        for dc in (mem_dc, src_dc):
            try:
                if dc is not None:
                    dc.DeleteDC()
            except Exception:
                pass
        try:
            win32gui.ReleaseDC(desktop, src_hdc)
        except Exception:
            pass


def _draw_cursor(win32gui, hdc, vx, vy):
    """Рисует текущий курсор в кадр. Тихо выходит, если курсор скрыт."""
    try:
        flags, hcursor, pos = win32gui.GetCursorInfo()
    except Exception:
        return
    if not flags or not hcursor:            # CURSOR_SHOWING == 1
        return
    hbm_mask = hbm_color = None
    try:
        info = win32gui.GetIconInfo(hcursor)
        hot_x, hot_y = info[1], info[2]
        hbm_mask, hbm_color = info[3], info[4]
        win32gui.DrawIconEx(hdc, pos[0] - vx - hot_x, pos[1] - vy - hot_y,
                            hcursor, 0, 0, 0, None, _DI_NORMAL)
    except Exception:
        pass
    finally:
        # GetIconInfo отдаёт КОПИИ битмапов — не удалить их значит течь.
        for hbm in (hbm_mask, hbm_color):
            try:
                if hbm:
                    win32gui.DeleteObject(hbm)
            except Exception:
                pass


def _grab_qt():
    """Запасной захват средствами Qt: по экрану за раз, склейкой."""
    rect = virtual_rect()
    out = QPixmap(rect.size())
    if out.isNull():
        return None
    out.fill()
    p = QPainter(out)
    try:
        for s in QGuiApplication.screens():
            g = s.geometry()
            shot = s.grabWindow(0)
            if shot.isNull():
                continue
            shot.setDevicePixelRatio(1.0)
            p.drawPixmap(g.x() - rect.x(), g.y() - rect.y(),
                         shot.scaled(g.size()))
    finally:
        p.end()
    return out
