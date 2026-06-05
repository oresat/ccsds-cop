"""Finite State Machine implementation for COP-1 service state machines."""
from collections.abc import Callable
from enum import Enum, IntEnum
from typing import Generic, NamedTuple, TypeVar

from .util import logger


class CopState(Enum):
    """Base class for COP service states."""


class CopEvent(IntEnum):
    """Base class for COP service events."""


T = TypeVar("T", bound=CopState)
U = TypeVar("U", bound=CopEvent)


class TransitionFrom(NamedTuple, Generic[T, U]):
    """Represents a transition from a state due to an event."""

    from_state: T
    event: U


class TransitionTo(NamedTuple, Generic[T]):
    """Represents the end of a transition to a state, and the actions executed on transition."""

    to_state: T
    actions: list[Callable[[], None]]


class StateMachine(Generic[T, U]):
    """An abstract state machine."""

    def __init__(self, initial_state: T) -> None:
        """Initialize the state machine.

        Parameters
        ----------
        initial_state
            The initial state of the state machine.
        """
        self._current_state: T = initial_state
        self._transition_map: dict[TransitionFrom[T, U], TransitionTo[T]] = {}

    @property
    def current_state(self) -> T:
        """Get the current state of the state machine.

        Returns
        -------
        T
            The current state of the state machine.
        """
        return self._current_state

    def process_event(self, event: U) -> None:
        """Process an event for this state machine.

        An event does not have to change state, or execute actions, but if it exists, it will be
        processed.

        Parameters
        ----------
        event
            The event to process.
        """
        # FIXME KeyError if the current state and passed event do not exist
        logger.debug(f"Event received: {event.name}")
        transition = self._transition_map[TransitionFrom(self._current_state, event)]
        for action in transition.actions:
            action()
        self.transition_to(transition.to_state)
        self._current_state = transition.to_state

    def add_transition(self, t_from: TransitionFrom[T, U], t_to: TransitionTo[T]) -> None:
        """Add a transition to the state machine.

        Parameters
        ----------
        t_from
            The state of the FSM at the start of the transition.
        t_to
            The state of the FSM at the end of the transition and any action to take during
            transition.
        """
        self._transition_map[t_from] = t_to

    def transition_to(self, state: T) -> None:
        """Transition to the given state, without an event or triggering any actions.

        Parameters
        ----------
        state
            The state to transition to.
        """
        self._current_state = state
