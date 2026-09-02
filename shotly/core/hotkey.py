"""
Глобальные горячие клавиши.

Основной путь — системный RegisterHotKey: Windows сама следит за сочетанием и
шлёт нам WM_HOTKEY. Никакого хука клавиатуры не ставится вообще, поток ввода
программа не трогает, ничего не подавляет и не переигрывает — чужие нажатия
идут мимо нас.

Раньше здесь был низкоуровневый хук библиотеки `keyboard` с suppress=True. Он
пропускает через себя КАЖДОЕ нажатие в системе и, подавляя своё сочетание,
переигрывает остальные события вручную — из-за чего модификатор мог «залипнуть»
(система считала Ctrl зажатым). Ради одной горячей клавиши это слишком дорого и
слишком рискованно.

Плата за RegisterHotKey — эксклюзивность: занятое другой программой сочетание не
регистрируется. На такой случай остался фолбэк на `keyboard`, но уже БЕЗ
suppress: хук только слушает и ничего не глотает.

Регистрация живёт в отдельном потоке с циклом сообщений: RegisterHotKey с
hWnd=NULL адресует WM_HOTKEY именно тому потоку, который вызвал регистрацию,
поэтому регистрировать и читать сообщения нужно в одном месте.
"""

import ctypes
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

# --- WinAPI ------------------------------------------------------------ #
_WM_HOTKEY = 0x0312
_WM_RELOAD = 0x0400 + 1          # WM_USER + 1: «перечитай список сочетаний»
_WM_QUIT_THREAD = 0x0400 + 2

_MOD = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
_MOD_NOREPEAT = 0x4000           # автоповтор при удержании нам не нужен

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Виртуальные коды клавиш, которые может назначить пользователь.
_VK = {
    "print screen": 0x2C, "escape": 0x1B, "space": 0x20, "enter": 0x0D,
    "tab": 0x09, "backspace": 0x08, "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "page up": 0x21, "page down": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pause": 0x13, "scroll lock": 0x91,
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA,
    "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "`": 0xC0,
}


def _vk_for(key):
    """Виртуальный код клавиши по её имени или 0, если имя незнакомое."""
    key = (key or "").strip().lower()
    if not key:
        return 0
    if key in _VK:
        return _VK[key]
    if key.startswith("f") and key[1:].isdigit():
        num = int(key[1:])
        if 1 <= num <= 24:
            return 0x70 + num - 1
    if len(key) == 1 and (key.isdigit() or "a" <= key <= "z"):
        return ord(key.upper())
    return 0


def parse(combo):
    """'ctrl+shift+s' -> (маска модификаторов, VK). (0, 0) — разобрать не вышло."""
    mods, vk = 0, 0
    for part in (combo or "").split("+"):
        part = part.strip().lower()
        if not part:
            continue
        if part in _MOD:
            mods |= _MOD[part]
        else:
            vk = _vk_for(part)
            if not vk:
                return 0, 0
    return (mods, vk) if vk else (0, 0)


# ---------------------------------------------------------------------- #
class _HotkeyThread(threading.Thread):
    """Поток с циклом сообщений: регистрирует сочетания и ловит WM_HOTKEY."""

    def __init__(self, on_fired, on_failed):
        super().__init__(daemon=True)
        self._on_fired = on_fired            # (key_id) -> None, ЧУЖОЙ поток
        self._on_failed = on_failed          # (list[key_id]) -> None
        self._lock = threading.Lock()
        self._wanted = []                    # [(key_id, combo)]
        self._registered = []                # id, уже зарегистрированные в системе
        self._tid = 0
        self._ready = threading.Event()

    # --- вызывается из UI-потока -------------------------------------- #
    def set_bindings(self, bindings):
        with self._lock:
            self._wanted = list(bindings)
        self._post(_WM_RELOAD)

    def shutdown(self):
        self._post(_WM_QUIT_THREAD)

    def _post(self, message):
        self._ready.wait(2.0)
        if not self._tid:
            return
        _user32.PostThreadMessageW(self._tid, message, 0, 0)

    # --- поток --------------------------------------------------------- #
    def run(self):
        self._tid = _kernel32.GetCurrentThreadId()
        # Очередь сообщений у потока появляется лениво — при первом обращении к
        # ней. Без этого PostThreadMessage сразу после старта потерялся бы.
        msg = wintypes.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._ready.set()

        while True:
            got = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got in (0, -1):
                break
            if msg.message == _WM_HOTKEY:
                self._on_fired(int(msg.wParam))
            elif msg.message == _WM_RELOAD:
                self._reload()
            elif msg.message == _WM_QUIT_THREAD:
                break
        self._unregister_all()

    def _reload(self):
        self._unregister_all()
        with self._lock:
            wanted = list(self._wanted)

        failed = []
        for key_id, combo in wanted:
            mods, vk = parse(combo)
            if not vk:
                failed.append(key_id)
                continue
            if _user32.RegisterHotKey(None, key_id, mods | _MOD_NOREPEAT, vk):
                self._registered.append(key_id)
            else:
                failed.append(key_id)       # сочетание занято другой программой
        if failed:
            self._on_failed(failed)

    def _unregister_all(self):
        for key_id in self._registered:
            _user32.UnregisterHotKey(None, key_id)
        self._registered = []


# ---------------------------------------------------------------------- #
class HotkeyManager(QObject):
    capture   = Signal()      # выделение области
    full_save = Signal()      # весь экран -> файл
    full_copy = Signal()      # весь экран -> буфер

    _IDS = {1: "capture", 2: "full_save", 3: "full_copy"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._fallback = None                # модуль keyboard, если пришлось
        self._fallback_handles = []
        self._combos = {}                    # key_id -> сочетание

    # ------------------------------------------------------------------ #
    def apply(self, settings):
        """Перерегистрирует сочетания под текущие настройки."""
        bindings = []
        if settings.get("hotkey_enabled"):
            bindings.append((1, settings.get("hotkey", "")))
        if settings.get("hotkey_fullsave_on"):
            bindings.append((2, settings.get("hotkey_fullsave", "")))
        if settings.get("hotkey_fullcopy_on"):
            bindings.append((3, settings.get("hotkey_fullcopy", "")))
        bindings = [(i, c.strip()) for i, c in bindings if c and c.strip()]

        self._drop_fallback()
        self._combos = dict(bindings)

        if self._thread is None:
            self._thread = _HotkeyThread(self._fire, self._on_failed)
            self._thread.start()
        self._thread.set_bindings(bindings)

    def stop(self):
        self._drop_fallback()
        self._combos = {}
        if self._thread is not None:
            self._thread.shutdown()
            self._thread = None

    # ------------------------------------------------------------------ #
    def _fire(self, key_id):
        """Колбэк из потока сообщений: emit уходит в UI-поток очередью."""
        name = self._IDS.get(key_id)
        if name:
            getattr(self, name).emit()

    def _on_failed(self, failed):
        """Сочетание занято системой или другой программой. Пробуем слушать его
        хуком — он не эксклюзивен. Хук только слушает: ничего не подавляем, иначе
        вернулись бы к залипающим модификаторам."""
        try:
            import keyboard
        except Exception:
            return
        self._fallback = keyboard
        for key_id in failed:
            combo = self._combos.get(key_id)
            if not combo:
                continue
            try:
                self._fallback_handles.append(
                    keyboard.add_hotkey(combo, self._fire, args=(key_id,),
                                        suppress=False))
            except Exception:
                continue

    def _drop_fallback(self):
        kb, handles = self._fallback, self._fallback_handles
        self._fallback_handles = []
        if kb is None:
            return
        for handle in handles:
            try:
                kb.remove_hotkey(handle)
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
