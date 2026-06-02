from collections.abc import Callable
from enum import Enum, IntEnum
from typing import Generic, NamedTuple, TypeVar

from .util import logger


class CopState(Enum):
    pass


class CopEvent(IntEnum):
    pass


T = TypeVar("T", bound=CopState)
U = TypeVar("U", bound=CopEvent)


class TransitionFrom(NamedTuple, Generic[T, U]):
    from_state: T
    event: U


class TransitionTo(NamedTuple, Generic[T]):
    to_state: T
    actions: list[Callable[[], None]]


class StateMachine(Generic[T, U]):
    def __init__(self, initial_state: T) -> None:
        self._current_state: T = initial_state
        self._transition_map: dict[TransitionFrom[T, U], TransitionTo[T]] = {}

    @property
    def current_state(self) -> T:
        return self._current_state

    def process_event(self, event: U) -> None:
        logger.debug(f"Event received: {event.name}")
        transition = self._transition_map[TransitionFrom(self._current_state, event)]
        for action in transition.actions:
            action()
        self.transition_to(transition.to_state)
        self._current_state = transition.to_state

    def add_transition(self, t_from: TransitionFrom[T, U], t_to: TransitionTo[T]) -> None:
        self._transition_map[t_from] = t_to

    def transition_to(self, state: T) -> None:
        self._current_state = state
