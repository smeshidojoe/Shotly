"""
Единственный экземпляр программы.

Именованный мьютекс: первый запуск его создаёт, второй видит занятым и молча
выходит. Его же видит установщик (AppMutex в shotly_setup.iss) и закрывает
программу перед заменой exe.

Второй запуск НИЧЕГО не делает с уже работающей программой. Раньше он просил её
снять скриншот — из-за этого повторный старт (ярлык плюс автозапуск, клик по
ярлыку при уже запущенной программе) сам открывал оверлей. Съёмка начинается
только по горячей клавише или по клику на иконке в трее.
"""

from .constants import INSTANCE_MUTEX

_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """Держит мьютекс до конца процесса."""

    def __init__(self):
        self._mutex = None
        self._is_first = self._take_mutex()

    def _take_mutex(self):
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.windll.kernel32
            k.CreateMutexW.restype = wintypes.HANDLE
            k.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL,
                                       wintypes.LPCWSTR]
            # Дескриптор держим до конца процесса: закрытие освободит имя, и
            # третий запуск счёл бы себя первым.
            self._mutex = k.CreateMutexW(None, False, INSTANCE_MUTEX)
            return k.GetLastError() != _ERROR_ALREADY_EXISTS
        except Exception:
            return True          # не Windows или сбой — запуск не блокируем

    def is_first(self):
        return self._is_first
