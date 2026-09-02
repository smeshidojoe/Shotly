"""
Сохранение снимка, копирование в буфер и печать.
"""

import os
import time

from PySide6.QtGui import QGuiApplication

from .constants import APP_NAME

_EXT = {"png": "png", "jpg": "jpg", "bmp": "bmp"}
# Qt называет формат JPEG, а расширение файла принято писать .jpg.
_QT_FMT = {"png": "PNG", "jpg": "JPEG", "bmp": "BMP"}


def build_name(settings, when=None):
    """Имя файла без расширения по шаблону из настроек."""
    tpl = settings.get("filename_template") or f"{APP_NAME}_%Y-%m-%d_%H-%M-%S"
    try:
        name = time.strftime(tpl, time.localtime(when or time.time()))
    except (ValueError, TypeError):
        name = time.strftime(f"{APP_NAME}_%Y-%m-%d_%H-%M-%S")
    # Символы, запрещённые в именах файлов Windows.
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "-")
    return name.strip() or APP_NAME


def unique_path(folder, base, ext):
    """folder/base.ext; при совпадении — base (2).ext, base (3).ext, ..."""
    path = os.path.join(folder, f"{base}.{ext}")
    i = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({i}).{ext}")
        i += 1
    return path


def default_path(settings):
    """Куда сохранили бы без вопросов. Папку создаём заранее."""
    fmt = settings.get("image_format", "png")
    folder = settings.get("save_dir") or os.path.expanduser("~")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.expanduser("~")
    return unique_path(folder, build_name(settings), _EXT.get(fmt, "png"))


def save_pixmap(pixmap, path, settings):
    """Пишет файл. Формат — по расширению пути, а не по настройке: пользователь
    мог сменить его прямо в диалоге сохранения. True при успехе."""
    if pixmap is None or pixmap.isNull() or not path:
        return False
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext == "jpeg":
        ext = "jpg"
    fmt = _QT_FMT.get(ext, _QT_FMT.get(settings.get("image_format", "png"), "PNG"))
    quality = int(settings.get("jpeg_quality", 92)) if fmt == "JPEG" else -1
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        return bool(pixmap.save(path, fmt, quality))
    except OSError:
        return False


def copy_to_clipboard(pixmap):
    """Кладёт картинку в буфер. Буфер живёт, пока живо приложение (оно в трее)."""
    if pixmap is None or pixmap.isNull():
        return False
    try:
        QGuiApplication.clipboard().setPixmap(pixmap)
        return True
    except Exception:
        return False


def print_pixmap(pixmap, parent=None):
    """Показывает системный диалог печати и печатает снимок по центру страницы."""
    if pixmap is None or pixmap.isNull():
        return False
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPainter
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    except Exception:
        return False

    printer = QPrinter(QPrinter.HighResolution)
    dlg = QPrintDialog(printer, parent)
    if dlg.exec() != QPrintDialog.Accepted:
        return False

    painter = QPainter()
    if not painter.begin(printer):
        return False
    try:
        page = painter.viewport()
        # Вписываем снимок в страницу, сохраняя пропорции; мелкие не растягиваем.
        scaled = pixmap.size().scaled(page.size(), Qt.KeepAspectRatio)
        x = page.x() + (page.width() - scaled.width()) // 2
        y = page.y() + (page.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled.width(), scaled.height(), pixmap)
    finally:
        painter.end()
    return True
