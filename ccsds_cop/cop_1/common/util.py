import logging
from collections import deque
from typing import TypeVar

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

T = TypeVar("T")


class BoundedDeque(deque[T]):
    def __init__(self, maxlen: int) -> None:
        super().__init__()
        self._maxlen = maxlen

    def try_append(self, item: T) -> bool:
        if len(self) >= self._maxlen:
            return False
        super().append(item)
        return True

    def try_appendleft(self, item: T) -> bool:
        if len(self) >= self._maxlen:
            return False
        super().appendleft(item)
        return True
