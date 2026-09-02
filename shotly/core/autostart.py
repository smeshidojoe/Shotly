r"""
Автозапуск при старте Windows через HKCU\...\CurrentVersion\Run.

Без прав администратора. В dev-режиме (не собранный exe) реестр не трогаем,
иначе в автозапуск прописался бы python.exe.
"""

import os
import sys

from .constants import APP_NAME

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _is_frozen():
    return bool(getattr(sys, "frozen", False))


def is_enabled():
    if not _is_frozen():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
        return True
    except OSError:
        return False


def set_enabled(on):
    """Включает или выключает автозапуск. True при успехе (и в dev, где
    регистрировать нечего).

    Включение всегда ПЕРЕЗАПИСЫВАЕТ значение: после переустановки в другую папку
    или обновления в реестре мог остаться путь к старому exe, и автозапуск молча
    перестал бы работать."""
    if not _is_frozen():
        return True
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            if on:
                exe = os.path.abspath(sys.executable)
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
