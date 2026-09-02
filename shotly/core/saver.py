"""
Сохранение снимка, копирование в буфер и печать.
"""

import os
import re
import time

from PySide6.QtGui import QGuiApplication

from .constants import APP_NAME

_EXT = {"png": "png", "jpg": "jpg", "bmp": "bmp"}
# Qt называет формат JPEG, а расширение файла принято писать .jpg.
_QT_FMT = {"png": "PNG", "jpg": "JPEG", "bmp": "BMP"}

# Занятым считаем номер в любом из наших форматов: Screenshot_7.jpg должен
# помешать выдать номер 7 файлу .png, иначе в папке окажутся два «седьмых».
_SCAN_EXTS = {"png", "jpg", "jpeg", "bmp"}

DEFAULT_TEMPLATE = "Screenshot_%n"

# %n — порядковый номер, %03n — он же с ведущими нулями.
_NUM_RE = re.compile(r"%(?:0(\d+))?n")
# Место номера в уже развёрнутом шаблоне. Символ управляющий: в имени файла его
# быть не может, поэтому спутать с настоящим текстом нельзя.
_MARK = "\x01"

_BAD_CHARS = r'\/:*?"<>|'


def _expand(settings, when=None):
    """Шаблон -> (имя с маркером номера, ширина номера). Маркера нет, если в
    шаблоне не было %n."""
    tpl = settings.get("filename_template") or DEFAULT_TEMPLATE

    match = _NUM_RE.search(tpl)
    width = int(match.group(1)) if (match and match.group(1)) else 0
    if match:
        # Номер в имени ровно один: второй превратил бы поиск свободного в
        # перебор пар, а пользы никакой.
        tpl = _NUM_RE.sub(_MARK, tpl, count=1)
        tpl = _NUM_RE.sub("", tpl)

    try:
        name = time.strftime(tpl, time.localtime(when or time.time()))
    except (ValueError, TypeError):
        # Незнакомый код в шаблоне: не роняем сохранение, берём заводской.
        name = time.strftime(DEFAULT_TEMPLATE.replace("%n", _MARK))
        width = 0

    for ch in _BAD_CHARS:                    # запрещённые в именах Windows
        name = name.replace(ch, "-")
    return (name.strip() or APP_NAME), width


def _free_number(folder, marked, width):
    """Наименьший свободный номер в папке для имени с маркером.

    Считаем от единицы, а не «последний + 1»: удалили Screenshot_134 — следующий
    снимок займёт именно его место, и дыр в нумерации не остаётся.
    """
    head, _, tail = marked.partition(_MARK)
    pattern = re.compile("%s(\\d+)%s$" % (re.escape(head), re.escape(tail)),
                         re.IGNORECASE)
    used = set()
    try:
        entries = os.listdir(folder)
    except OSError:
        entries = []
    for entry in entries:
        stem, ext = os.path.splitext(entry)
        if ext[1:].lower() not in _SCAN_EXTS:
            continue
        found = pattern.match(stem)
        if found:
            used.add(int(found.group(1)))

    number = 1
    while number in used:
        number += 1
    return "%0*d" % (width, number) if width else str(number)


def build_name(settings, when=None, folder=None):
    """Имя файла без расширения по шаблону из настроек. folder нужен только для
    шаблонов с %n — по нему ищется свободный номер."""
    name, width = _expand(settings, when)
    if _MARK not in name:
        return name
    folder = folder if folder is not None else (settings.get("save_dir") or "")
    return name.replace(_MARK, _free_number(folder, name, width))


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
    return unique_path(folder, build_name(settings, folder=folder),
                       _EXT.get(fmt, "png"))


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
