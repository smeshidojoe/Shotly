"""
Единственный экземпляр программы и связь с уже запущенным.

Два разных механизма, и оба нужны:

  * именованный мьютекс — решает, кто первый. Его же видит установщик
    (AppMutex в shotly_setup.iss) и закрывает программу перед заменой exe;
  * локальный сокет — канал к первому экземпляру. Программа живёт в трее, и
    повторный запуск ярлыка выглядел бы как «ничего не произошло». Вместо этого
    второй экземпляр говорит первому «сделай снимок» и выходит.
"""

import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .constants import INSTANCE_MUTEX

_ERROR_ALREADY_EXISTS = 183
_CONNECT_TIMEOUT_MS = 400

# Команда, которую шлёт второй экземпляр.
CMD_CAPTURE = b"capture"


class SingleInstance(QObject):
    """Держит мьютекс и (у первого экземпляра) слушает локальный сокет."""

    woken = Signal()          # пришла команда от второго экземпляра

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = None
        self._server = None
        self._is_first = self._take_mutex()

    # ------------------------------------------------------------------ #
    def _take_mutex(self):
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.windll.kernel32
            k.CreateMutexW.restype = wintypes.HANDLE
            k.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL,
                                       wintypes.LPCWSTR]
            # Дескриптор держим до конца процесса: закрытие освободит имя.
            self._mutex = k.CreateMutexW(None, False, INSTANCE_MUTEX)
            return k.GetLastError() != _ERROR_ALREADY_EXISTS
        except Exception:
            return True          # не Windows или сбой — запуск не блокируем

    def is_first(self):
        return self._is_first

    # ------------------------------------------------------------------ #
    def listen(self):
        """Первый экземпляр начинает принимать команды. Тихо ничего не делает,
        если сокет занять не удалось — программа и без канала работоспособна."""
        if not self._is_first or self._server is not None:
            return False
        try:
            # Прошлый экземпляр мог упасть, не убрав за собой имя сокета.
            QLocalServer.removeServer(INSTANCE_MUTEX)
            server = QLocalServer(self)
            if not server.listen(INSTANCE_MUTEX):
                return False
            server.newConnection.connect(self._on_connection)
            self._server = server
            return True
        except Exception:
            return False

    def _on_connection(self):
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda c=conn: self._on_ready(c))
        conn.disconnected.connect(conn.deleteLater)

    def _on_ready(self, conn):
        data = bytes(conn.readAll())
        conn.disconnectFromServer()
        if CMD_CAPTURE in data:
            self.woken.emit()

    # ------------------------------------------------------------------ #
    @staticmethod
    def wake_running(command=CMD_CAPTURE):
        """Вызывается ВТОРЫМ экземпляром: разбудить первый и уйти."""
        sock = QLocalSocket()
        sock.connectToServer(INSTANCE_MUTEX)
        if not sock.waitForConnected(_CONNECT_TIMEOUT_MS):
            return False
        sock.write(command)
        sock.flush()
        sock.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
        sock.disconnectFromServer()
        return True

    def close(self):
        if self._server is not None:
            self._server.close()
            self._server = None
        # Мьютекс отпускает сама ОС при выходе процесса; закрывать вручную
        # незачем и опасно — гонка с установщиком, который на него смотрит.
        if sys.platform != "win32":
            self._mutex = None
