"""
Палитра, масштаб интерфейса и QSS.

Приложение запускается с отключённым масштабированием Qt (QT_ENABLE_HIGHDPI_SCALING=0,
см. main.py): оверлею нужны физические пиксели один в один, иначе снимок и рамка
выделения разъезжаются на мониторах со 125–200%. Плата за это — окна пришлось бы
рисовать мелкими, поэтому масштаб считаем сами из DPI экрана и множим на него все
размеры (см. scale() и s()).
"""

from PySide6.QtGui import QColor, QCursor, QGuiApplication

# --- палитра ---------------------------------------------------------- #
PALETTE = {
    "bg":        "#1e2126",   # фон окна
    "panel":     "#24282e",   # карточки, панели инструментов
    "field":     "#2b3038",   # поля ввода, выпадающие списки
    "field_hi":  "#333944",   # то же под курсором
    "border":    "#3a414c",
    "text":      "#e6e9ee",
    "text_dim":  "#98a1ad",
    "accent":    "#4f8cff",
    "on_accent": "#ffffff",
    "danger":    "#e05a5a",
    "shadow":    "#0d0f12",
}

# Оверлей съёмки живёт поверх ЧУЖОГО изображения, поэтому фирменный синий там не
# работает: на синем фоне рамка пропадает, на светлом — спорит с картинкой.
# Разметка выделения нейтральная: белый штрих поверх чёрного даёт «муравьёв»,
# видимых на любом кадре. Иконку приложения это не касается — она остаётся синей.
OVERLAY = {
    "line":       "#ffffff",   # штрих рамки
    "line_under": "#000000",   # подложка под штрих
    "handle":     "#ffffff",   # заливка ручек
    "handle_edge": "#1a1a1a",  # обводка ручек
    "active":     "#ffffff",   # выбранный инструмент на панели
    "on_active":  "#1c1f24",   # иконка на выбранном инструменте
}
DASH = [4, 4]                  # длина штриха и пропуска рамки, px макета


def color(key):
    return QColor(PALETTE[key])


# --- масштаб ----------------------------------------------------------- #
_BASE_DPI = 96.0
_cached = None


def scale():
    """Множитель размеров интерфейса от DPI экрана под курсором (1.0 при 100%)."""
    global _cached
    if _cached is not None:
        return _cached
    try:
        screen = QGuiApplication.screenAt(QCursor.pos()) or \
                 QGuiApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch() if screen else _BASE_DPI
    except Exception:
        dpi = _BASE_DPI
    # За пределами 1.0–3.0 масштаб — почти наверняка мусор от драйвера монитора.
    _cached = max(1.0, min(3.0, (dpi or _BASE_DPI) / _BASE_DPI))
    return _cached


def invalidate_scale():
    """Сбросить кэш: монитор или его масштаб сменились."""
    global _cached
    _cached = None


def s(px):
    """Размер в px макета -> размер на текущем экране."""
    return max(1, int(round(px * scale())))


def font_px(px):
    return s(px)


# --- QSS ---------------------------------------------------------------- #
def stylesheet():
    """Оформление окон настроек и «О программе»."""
    from . import icons
    p = PALETTE
    check = icons.check_mark_path(s(14), p["on_accent"])
    return f"""
    QWidget {{
        background: transparent;
        color: {p['text']};
        font-family: "Segoe UI";
        font-size: {s(13)}px;
    }}
    QLabel[dim="true"] {{ color: {p['text_dim']}; }}
    QLabel[head="true"] {{
        color: {p['text_dim']};
        font-size: {s(11)}px;
        text-transform: uppercase;
    }}

    QLineEdit, QComboBox, QSpinBox {{
        background: {p['field']};
        border: 1px solid {p['border']};
        border-radius: {s(7)}px;
        padding: {s(6)}px {s(9)}px;
        selection-background-color: {p['accent']};
        selection-color: {p['on_accent']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border-color: {p['accent']};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        color: {p['text_dim']};
        background: {p['bg']};
    }}
    QComboBox::drop-down {{ border: none; width: {s(20)}px; }}
    QComboBox QAbstractItemView {{
        background: {p['field']};
        border: 1px solid {p['border']};
        border-radius: {s(7)}px;
        padding: {s(4)}px;
        outline: none;
        selection-background-color: {p['accent']};
        selection-color: {p['on_accent']};
    }}

    QPushButton {{
        background: {p['field']};
        border: 1px solid {p['border']};
        border-radius: {s(7)}px;
        padding: {s(7)}px {s(16)}px;
    }}
    QPushButton:hover  {{ background: {p['field_hi']}; }}
    QPushButton:disabled {{ color: {p['text_dim']}; }}
    QPushButton[accent="true"] {{
        background: {p['accent']};
        border-color: {p['accent']};
        color: {p['on_accent']};
    }}
    QPushButton[accent="true"]:hover {{ background: #6099ff; }}
    QPushButton[flat="true"] {{
        background: transparent;
        border: none;
        color: {p['text_dim']};
        padding: {s(4)}px {s(6)}px;
    }}
    QPushButton[flat="true"]:hover {{ color: {p['text']}; }}

    QCheckBox {{ spacing: {s(9)}px; }}
    QCheckBox:disabled {{ color: {p['text_dim']}; }}
    QCheckBox::indicator {{
        width: {s(16)}px; height: {s(16)}px;
        border: 1px solid {p['border']};
        border-radius: {s(4)}px;
        background: {p['field']};
    }}
    QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
    QCheckBox::indicator:checked {{
        background: {p['accent']};
        border-color: {p['accent']};
        image: url({check});
    }}

    QSlider::groove:horizontal {{
        height: {s(4)}px;
        background: {p['field']};
        border-radius: {s(2)}px;
    }}
    QSlider::sub-page:horizontal {{
        background: {p['accent']};
        border-radius: {s(2)}px;
    }}
    QSlider::handle:horizontal {{
        width: {s(14)}px; height: {s(14)}px;
        margin: -{s(5)}px 0;
        border-radius: {s(7)}px;
        background: {p['text']};
    }}

    QToolTip {{
        background: {p['panel']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: {s(4)}px {s(7)}px;
    }}
    """
