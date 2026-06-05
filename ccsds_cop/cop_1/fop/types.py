"""Various type definitions for FOP-1."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto, unique
from typing import TYPE_CHECKING

from ..common.fsm import CopState
from ..common.service import Indication
from ..common.util import BoundedDeque

if TYPE_CHECKING:
    from spacepackets.uslp import BypassSequenceControlFlag, ProtocolCommandFlag

    from ..common.ccsds import Gvcid


@unique
class FopState(CopState):
    """The state of FOP-1.

    CCSDS 232.1-B-2 § 5.1.2
    """

    ACTIVE = 1
    RETRANSMIT_NO_WAIT = 2
    RETRANSMIT_WITH_WAIT = 3
    INITIALIZING_NO_BC = 4
    INITIALIZING_WITH_BC = 5
    INITIAL = 6


@unique
class Alert(Enum):
    """FOP-1 Alert types.

    See CCSDS 232.1-B-2 Table 4-4.
    """

    LIMIT = 0
    T1 = 1
    LOCKOUT = 2
    SYNCH = 3
    NNR = 4
    CLCW = 5
    LLIF = 6
    TERM = 7


class ServiceType(Enum):
    """The service type for FDU signals."""

    AD = auto()
    BD = auto()


class NotificationType(Enum):
    """Notification Types for Transfer Notification Signals.

    See CCSDS 232.1-B-2 Tables 4-5 and 4-6.
    """

    ACCEPT = auto()
    REJECT = auto()
    POSITIVE_CONFIRM = auto()
    NEGATIVE_CONFIRM = auto()


class AsyncNotificationType(Enum):
    """Notification Types for Async_Notify indications.

    See CCSDS 232.1-B-2 Table 4-3.
    """

    ALERT = auto()
    SUSPEND = auto()


class DirectiveType(Enum):
    """Direct Request types.

    See CCSDS 232.1-B-2 Table 4-1.
    """

    INITIATE_AD_NO_CLCW = auto()
    INITIATE_AD_WITH_CLCW = auto()
    INITIATE_AD_WITH_UNLOCK = auto()
    INITIATE_AD_WITH_SET_V_R = auto()
    TERMINATE_AD = auto()
    RESUME_AD = auto()
    SET_V_S = auto()
    SET_SLIDING_WINDOW_WIDTH = auto()
    SET_T1 = auto()
    SET_TRANSMISSION_LIMIT = auto()
    SET_TIMEOUT_TYPE = auto()


class ResponseType(Enum):
    """The type of Response signal."""

    AD_ACCEPTED = auto()
    AD_REJECTED = auto()
    BC_ACCEPTED = auto()
    BC_REJECTED = auto()
    BD_ACCEPTED = auto()
    BD_REJECTED = auto()


@dataclass
class DirectiveNotification(Indication):
    """A signal to the Higher Procedures to notify an event associated with a Directive."""

    request_id: int
    notification_type: NotificationType


@dataclass
class DirectiveRequest(Indication):
    """A signal issues by the Higher Procedures to request FOP-1 to perform a directive."""

    request_id: int
    directive_type: DirectiveType
    directive_qualifier: int = 0


@dataclass
class RequestToTransferFdu(Indication):
    """A signal issues by the Higher Procedures to request FOP-1 to transfer an FDU."""

    request_id: int
    fdu: bytes
    service_type: ServiceType


@dataclass
class TransferNotification(Indication):
    """Notify the Higher Procedures of an event associated with an FDU."""

    request_id: int
    notification_type: NotificationType


@dataclass
class AbortRequest(Indication):
    """A signal to cancel any ongoing processes for Type-AD or BC frame of the Virtual Channel."""


@dataclass
class TransmitRequestForFrame(Indication):
    """A signal to the Lower Procedures to transmit a frame.

    See CCSDS 232.1-B-2 § 3.2.3.
    """

    bypass_flag: BypassSequenceControlFlag
    command_flag: ProtocolCommandFlag
    v_s: int
    tfdf: bytes


@dataclass
class AsyncNotification(Indication):
    """A signal to the Higher Procedures of an event asynchronous with requests.

    See CCSDS 232.1-B-2 § 3.2.2.2.4.

    Parameters
    ----------
    notification_type : AsyncNotificationType
        The type of notification.
    notification_qualifier : Alert | None
        Qualifier is the Notification Type's parameter.
        Alert has a "Reason Code" but Suspend has no params.
    """

    notification_type: AsyncNotificationType
    notification_qualifier: Alert | None


@dataclass
class Response(Indication):
    """A rReponse signal used for flow control with the Lower Procedures.

    See CCSDS 232.1-B-2 § 3.2.3.
    """

    response_type: ResponseType


@dataclass
class WaitQueueEntry:
    """An entry in the FOP Wait_Queue."""

    request_id: int
    gvcid: Gvcid
    fdu: bytes
    service_type: ServiceType


@dataclass
class SentQueueEntry:
    """An entry in the FOP Sent_Queue."""

    request_id: int  # to generate Transfer Notification back to Higher Procedures
    gvcid: Gvcid  # identifies which VC this frame belongs to
    tfdf: bytes  # the master copy for retransmission
    n_s: int  # N(S) sequence number, needed to track NN(R)
    to_be_retransmitted: bool = False  # from section 5.1.5


class FopInterface:
    """An interface for FOP signals to/from the Higher and Lower Procedures.

    Attributes
    ----------
    signal_queue : BoundedDeque[Indication]
        The inbound signal queue, from either the Higher or Lower procedures.
    to_higher: BoundedDeque[Indication]
        The outbound signal queue to the Higher Procedures.
    to_lower: BoundedDeque[Indication]
        The outbound signal queue to the Lower Procedures.
    """

    def __init__(self, size: int = 10) -> None:
        """Initialize the FOP interface.

        Parameters
        ----------
        size
            The size of the FOP signal buffers.
        """
        self.signal_queue: BoundedDeque[Indication] = BoundedDeque(size)
        self.to_higher: BoundedDeque[Indication] = BoundedDeque(size)
        self.to_lower: BoundedDeque[Indication] = BoundedDeque(size)
