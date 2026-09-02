# -*- mode: python ; coding: utf-8 -*-

import re

# --- версия ----------------------------------------------------------------- #
# Единственный источник — shotly/core/constants.py. Отдельный version_info.txt не
# заводим: он дублировал бы ту же строку и однажды разошёлся бы с реальностью.
_APP_VERSION = re.search(
    r'APP_VERSION\s*=\s*"([^"]+)"',
    open('shotly/core/constants.py', encoding='utf-8').read()).group(1)
_VER_TUPLE = tuple(int(x) for x in (_APP_VERSION.split('.') + ['0'] * 4)[:4])

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo)

_VERSION_RES = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_VER_TUPLE, prodvers=_VER_TUPLE,
                      mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'SmeshidoJoe'),
            StringStruct('FileDescription', 'Shotly'),
            StringStruct('FileVersion', _APP_VERSION),
            StringStruct('InternalName', 'Shotly'),
            StringStruct('LegalCopyright', '© 2026 SmeshidoJoe'),
            StringStruct('OriginalFilename', 'Shotly.exe'),
            StringStruct('ProductName', 'Shotly'),
            StringStruct('ProductVersion', _APP_VERSION),
        ])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ])

# Иконка приложения нужна в рантайме (трей, окно «О программе»): PyInstaller не
# считает её кодом и сам бы не положил. Кладём именно файл, а не всю папку
# assets: icon.png 1024 и обложка cover.png нужны странице проекта, а не exe.
_DATAS = [('assets/app.ico', 'assets')]

# win32ui/win32gui тянутся из pywin32 — анализатор находит их через core/capture.py,
# но win32ctypes ставит их отложенно, поэтому перечисляем явно.
_HIDDEN = ['win32ui', 'win32gui', 'win32api', 'win32con', 'win32print']

# В окружении разработчика обычно стоят и другие привязки Qt: PyInstaller не умеет
# класть в сборку два набора сразу и обрывает сборку. Ничего из этого не нужно.
# Pillow — только для tools/make_icon.py, в рантайме не участвует.
_EXCLUDES = [
    'PyQt5', 'PyQt6', 'PySide2', 'shiboken2',
    'matplotlib', 'tkinter', 'IPython', 'notebook', 'pytest',
    'PIL', 'numpy', 'pandas',
    # Тяжёлые куски Qt, которых у нас нет на экране.
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml',
    'PySide6.QtQuick', 'PySide6.Qt3DCore', 'PySide6.QtMultimedia',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtBluetooth',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtNetworkAuth',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_DATAS,
    hiddenimports=_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Shotly',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,              # программа живёт в трее, консоль не нужна
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\app.ico'],
    version=_VERSION_RES,
)
