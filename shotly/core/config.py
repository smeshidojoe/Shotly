import os
import json

from .constants import APP_DIR, CONFIG_PATH, default_save_dir


def defaults():
    return {
        # --- Основные ---------------------------------------------------- #
        "language":            "ru",       # ru | en
        "autostart":           False,
        # Показывать тост после копирования в буфер и сохранения файла.
        "notify":              True,
        # Запоминать рамку выделения между снимками (как в Lightshot).
        "remember_selection":  False,
        # Рисовать курсор мыши в кадре.
        "capture_cursor":      False,
        # Копировать в буфер сразу после сохранения файла.
        "copy_after_save":     False,

        # --- Горячие клавиши --------------------------------------------- #
        "hotkey_enabled":      True,
        "hotkey":              "print screen",     # выделение области
        "hotkey_fullsave_on":  False,
        "hotkey_fullsave":     "shift+print screen",   # весь экран -> файл
        "hotkey_fullcopy_on":  False,
        "hotkey_fullcopy":     "ctrl+print screen",    # весь экран -> буфер

        # --- Форматы ------------------------------------------------------ #
        "save_dir":            default_save_dir(),
        "image_format":        "png",      # png | jpg | bmp
        "jpeg_quality":        92,
        # Шаблон имени файла: коды strftime + %n (порядковый номер за секунду).
        "filename_template":   "Shotly_%Y-%m-%d_%H-%M-%S",
        # Спрашивать путь каждый раз (диалог сохранения) вместо тихой записи.
        "ask_where_to_save":   True,

        # --- Рисование ---------------------------------------------------- #
        "draw_color":          "#ff2d2d",
        "draw_width":          3,
        "last_tool":           "pen",

        # --- Обновления --------------------------------------------------- #
        "check_updates":       True,       # проверять при запуске
    }


_ENUMS = {
    "language":     ("ru", "en"),
    "image_format": ("png", "jpg", "bmp"),
    "last_tool":    ("pen", "line", "arrow", "rect", "marker", "text"),
}


def _num_in(v, lo, hi, fallback, integer=True):
    """Число в диапазоне [lo, hi] или fallback (bool числом не считаем)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return fallback
    if integer:
        if float(v) != int(v):
            return fallback
        v = int(v)
    return v if lo <= v <= hi else fallback


def validate(data):
    """Приводит настройки к рабочему виду: битое значение заменяется дефолтом."""
    d = defaults()

    # Общее правило: тип не совпал с типом дефолта — берём дефолт.
    for key, dv in d.items():
        if key not in data:
            continue
        v = data[key]
        if isinstance(dv, bool):
            ok = isinstance(v, bool)
        elif isinstance(dv, (int, float)):
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        else:
            ok = isinstance(v, type(dv))
        data[key] = v if ok else dv

    for key, allowed in _ENUMS.items():
        if data.get(key) not in allowed:
            data[key] = d[key]

    data["jpeg_quality"] = _num_in(data.get("jpeg_quality"), 10, 100, 92)
    data["draw_width"]   = _num_in(data.get("draw_width"), 1, 20, 3)

    if not str(data.get("save_dir") or "").strip():
        data["save_dir"] = d["save_dir"]
    if not str(data.get("filename_template") or "").strip():
        data["filename_template"] = d["filename_template"]

    # Пустое сочетание не зарегистрируется, а галочка выглядела бы рабочей.
    for key, flag in (("hotkey", "hotkey_enabled"),
                      ("hotkey_fullsave", "hotkey_fullsave_on"),
                      ("hotkey_fullcopy", "hotkey_fullcopy_on")):
        if not str(data.get(key) or "").strip():
            data[key] = d[key]
            data[flag] = False

    # Два одинаковых сочетания: второе просто не сработает — гасим дубли.
    seen = {}
    for key in ("hotkey", "hotkey_fullsave", "hotkey_fullcopy"):
        combo = data[key]
        if combo in seen:
            data[key] = d[key]
        seen[data[key]] = key

    if not str(data.get("draw_color") or "").startswith("#"):
        data["draw_color"] = d["draw_color"]

    return data


def load():
    """Читает настройки с диска, дополняя отсутствующие ключи дефолтами."""
    data = defaults()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            data.update(saved)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return validate(data)


def save(settings):
    """Сохраняет настройки на диск (тихо, без падений на ошибках ФС)."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
