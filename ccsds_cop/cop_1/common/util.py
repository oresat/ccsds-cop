"""Other utilities."""
import logging
from collections import deque
from typing import TypeVar

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

T = TypeVar("T")


class BoundedDeque(deque[T]):
    """Deque with bounded length that can be forced to exceed the length.

    Standard Python deque evicts items when adding past its length. This class allows,
    ideally temporarily, exceeding the maximum length without evicting any items.
    """

    def __init__(self, maxlen: int) -> None:
        """Initialize the deque with maximum length.

        Parameters
        ----------
        maxlen
            Maximum length of the deque.
        """
        super().__init__()
        self._maxlen = maxlen

    def try_append(self, item: T) -> bool:
        """Try to append an item to right side of the deque.

        Parameters
        ----------
        item
            The item to append.

        Returns
        -------
        bool
            True if the item was appended, False otherwise.
        """
        if len(self) >= self._maxlen:
            return False
        super().append(item)
        return True

    def try_appendleft(self, item: T) -> bool:
        """Try to append an item to left side of the deque.

        Parameters
        ----------
        item
            The item to append.

        Returns
        -------
        bool
            True if the item was appended, False otherwise.
        """
        if len(self) >= self._maxlen:
            return False
        super().appendleft(item)
        return True
