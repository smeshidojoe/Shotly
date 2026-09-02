"""
Лёгкая локализация.

Ключ перевода — английская строка (она же fallback). Любую видимую надпись
оборачиваем в tr("English text"). Непереведённая строка вернётся как есть.
"""

_RU = {
    # --- Трей / общее --------------------------------------------------- #
    "Take a screenshot":            "Сделать скриншот",
    "Capture full screen":          "Снимок всего экрана",
    "Settings...":                  "Настройки...",
    "About...":                     "О программе...",
    "Quit":                         "Выход",
    "Settings":                     "Настройки",
    "About":                        "О программе",
    "OK":                           "ОК",
    "Cancel":                       "Отмена",
    "Close":                        "Закрыть",
    "Browse...":                    "Обзор...",
    "Version":                      "Версия",

    # --- Вкладки настроек ------------------------------------------------ #
    "General":                      "Основные",
    "Hotkeys":                      "Горячие клавиши",
    "Formats":                      "Форматы",
    "Updates":                      "Обновления",

    # --- Основные -------------------------------------------------------- #
    "Launch at Windows startup":    "Запускать при старте Windows",
    "Show notifications about copying and saving":
        "Показывать уведомления о копировании и сохранении",
    "Remember selection position":  "Сохранять позицию выделенной области",
    "Capture mouse cursor":         "Сохранять курсор на скриншоте",
    "Copy to clipboard after saving": "Копировать в буфер после сохранения",
    "Language":                     "Язык",
    "Open screenshots folder":      "Открыть папку скриншотов",
    "Reset settings":               "Сбросить настройки",
    "Click again to confirm":       "Нажмите ещё раз для подтверждения",

    # --- Горячие клавиши ------------------------------------------------- #
    "Main hotkey":                  "Основная горячая клавиша",
    "Quick save of the whole screen": "Быстрое сохранение всего экрана",
    "Quick copy of the whole screen": "Быстрое копирование всего экрана",
    "Press a key combination":      "Нажмите сочетание клавиш",
    "This combination is already used": "Это сочетание уже занято",

    # --- Форматы --------------------------------------------------------- #
    "Save folder":                  "Папка сохранения",
    "Choose save folder":           "Выберите папку сохранения",
    "Image format":                 "Формат изображения",
    "JPEG quality":                 "Качество JPEG",
    "File name template":           "Шаблон имени файла",
    "%n — the first free number in the folder":
        "%n — первый свободный номер в папке",
    "Ask where to save every time": "Спрашивать путь при каждом сохранении",
    "Example":                      "Пример",
    "Save screenshot":              "Сохранить скриншот",
    "Images":                       "Изображения",

    # --- Обновления ------------------------------------------------------ #
    "Notify about new versions":    "Уведомлять о новых версиях",
    "Check now":                    "Проверить сейчас",
    "Checking...":                  "Проверка...",
    "You have the latest version":  "Установлена последняя версия",
    "Update available":             "Доступно обновление",
    "Click to install":             "Нажмите, чтобы установить",
    "Update failed":                "Не удалось обновить",
    "Downloading...":               "Загрузка...",
    "Install and restart":          "Установить и перезапустить",
    "Check failed":                 "Проверка не удалась",
    "Current version":              "Текущая версия",

    # --- Оверлей / тосты ------------------------------------------------- #
    "Copied to clipboard":          "Скопировано в буфер обмена",
    "Saved":                        "Сохранено",
    "Save failed":                  "Не удалось сохранить",
    "Nothing to capture":           "Нечего снимать",
    "Pen":                          "Карандаш",
    "Line":                         "Линия",
    "Arrow":                        "Стрелка",
    "Rectangle":                    "Прямоугольник",
    "Marker":                       "Маркер",
    "Text":                         "Текст",
    "Color":                        "Цвет",
    "Undo":                         "Отменить",
    "Print":                        "Печать",
    "Copy":                         "Копировать",
    "Save":                         "Сохранить",
    "Cancel capture":               "Отменить съёмку",
    "More colors...":               "Другие цвета...",
    "Line width":                   "Толщина линии",

    # --- О программе ----------------------------------------------------- #
    "A screenshot tool: select, draw, copy, save.":
        "Скриншоты: выделить, порисовать, скопировать, сохранить.",
    "Project page":                 "Страница проекта",
}

_LANGS = {"ru": _RU, "en": {}}

_current = "ru"


def set_language(lang):
    global _current
    _current = lang if lang in _LANGS else "en"


def language():
    return _current


def tr(text):
    return _LANGS.get(_current, {}).get(text, text)
