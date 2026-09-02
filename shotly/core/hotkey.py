"""
Глобальные горячие клавиши.

Библиотека `keyboard` ставит низкоуровневый хук и зовёт колбэк в СВОЁМ потоке,
поэтому в UI-поток уходим через Qt-сигнал (авто-queued). Системный
RegisterHotKey был бы дешевле, но он эксклюзивный: занятое другой программой
сочетание просто не зарегистрировалось бы. Хук срабатывает и в этом случае.

Регистрация идёт в фоновом потоке: `import keyboard` строит таблицы имён клавиш
и стоит заметные ~200 мс, а между запуском и первым нажатием времени всегда
больше.
"""

import threading

from PySide6.QtCore import QObject, Signal


class HotkeyManager(QObject):
    capture   = Signal()      # выделение области
    full_save = Signal()      # весь экран -> файл
    full_copy = Signal()      # весь экран -> буфер

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._kb = None
        self._handles = []
        self._wanted = []         # [(combo, signal)] — что регистрируем сейчас
        self._epoch = 0           # номер поколения: гасит гонку с прошлым apply

    # ------------------------------------------------------------------ #
    def apply(self, settings):
        """Перерегистрирует хоткеи под текущие настройки."""
        wanted = []
        if settings.get("hotkey_enabled"):
            wanted.append((settings.get("hotkey", ""), self.capture))
        if settings.get("hotkey_fullsave_on"):
            wanted.append((settings.get("hotkey_fullsave", ""), self.full_save))
        if settings.get("hotkey_fullcopy_on"):
            wanted.append((settings.get("hotkey_fullcopy", ""), self.full_copy))
        wanted = [(c.strip(), s) for c, s in wanted if c and c.strip()]

        with self._lock:
            self._epoch += 1
            epoch = self._epoch
            self._wanted = wanted
        self._unhook()
        threading.Thread(target=self._register, args=(epoch, wanted),
                         daemon=True).start()

    def stop(self):
        with self._lock:
            self._epoch += 1
            self._wanted = []
        self._unhook()

    # ------------------------------------------------------------------ #
    def _register(self, epoch, wanted):
        try:
            import keyboard
        except Exception:
            return
        with self._lock:
            if epoch != self._epoch:
                return                     # нас уже перенастроили
            self._kb = keyboard

        handles = []
        for combo, signal in wanted:
            # Гасим только PrintScreen: иначе Windows положит свой снимок в
            # буфер поверх нашего. Обычные сочетания не перехватываем — их может
            # ждать другая программа.
            suppress = "print screen" in combo.lower()
            try:
                handles.append(keyboard.add_hotkey(
                    combo, signal.emit, suppress=suppress))
            except Exception:
                continue

        with self._lock:
            if epoch == self._epoch:
                self._handles = handles
                return
        # Пока регистрировались, настройки успели смениться — снимаем сразу.
        for h in handles:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass

    def _unhook(self):
        with self._lock:
            kb, handles = self._kb, self._handles
            self._handles = []
        if kb is None:
            return
        for h in handles:
            try:
                kb.remove_hotkey(h)
            except Exception:
                pass


# ---------------------------------------------------------------------- #
#  Разбор и показ сочетаний
# ---------------------------------------------------------------------- #
# Порядок модификаторов фиксируем: 'ctrl+shift+alt+X' читается одинаково везде.
_MOD_ORDER = ("ctrl", "shift", "alt", "win")

_PRETTY = {
    "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win",
    "print screen": "Prnt Scrn", "escape": "Esc", "space": "Space",
    "backspace": "Backspace", "enter": "Enter", "tab": "Tab",
    "insert": "Insert", "delete": "Delete", "home": "Home", "end": "End",
    "page up": "Page Up", "page down": "Page Down",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
}


def pretty(combo):
    """'ctrl+print screen' -> 'Ctrl + Prnt Scrn'."""
    parts = [p.strip() for p in (combo or "").split("+") if p.strip()]
    out = []
    for p in parts:
        low = p.lower()
        out.append(_PRETTY.get(low, p.upper() if len(p) == 1 else p.capitalize()))
    return " + ".join(out)


def normalize(mods, key):
    """Собирает канонную строку из набора модификаторов и имени клавиши."""
    ordered = [m for m in _MOD_ORDER if m in mods]
    return "+".join(ordered + ([key] if key else []))
