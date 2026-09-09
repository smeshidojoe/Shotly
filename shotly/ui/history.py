"""
История правок оверлея: отмена и повтор.

Хранит не команды, а снимки состояния — список фигур и геометрию вставленной
картинки. Фигуры неизменяемы после создания (кроме картинки, которую двигают и
растягивают), поэтому снимок стоит копейки: это список ссылок плюс один
прямоугольник на картинку.

Такой подход честно отменяет и то, что командой не назовёшь, — перетаскивание
картинки, смену её размера, очистку всего кадра.
"""

from PySide6.QtCore import QRectF

# Глубже уже никто не отменяет, а память списки едят.
_LIMIT = 60


def snapshot(shapes):
    """Состояние, к которому можно вернуться."""
    return [(shape, QRectF(shape.rect) if shape.kind == "image" else None)
            for shape in shapes]


def restore(shapes, state):
    """Возвращает список фигур к снимку, на месте (список тот же объект)."""
    shapes[:] = [shape for shape, _rect in state]
    for shape, rect in state:
        if rect is not None:
            shape.rect = QRectF(rect)


class History:
    def __init__(self):
        self._undo = []
        self._redo = []

    def clear(self):
        self._undo.clear()
        self._redo.clear()

    def push(self, shapes):
        """Запомнить состояние ДО изменения. Новое действие обрывает ветку
        повтора — вернуться к отменённому уже нельзя, как везде."""
        self._undo.append(snapshot(shapes))
        if len(self._undo) > _LIMIT:
            del self._undo[0]
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self, shapes):
        if not self._undo:
            return False
        self._redo.append(snapshot(shapes))
        restore(shapes, self._undo.pop())
        return True

    def redo(self, shapes):
        if not self._redo:
            return False
        self._undo.append(snapshot(shapes))
        restore(shapes, self._redo.pop())
        return True
