"""The FOP-1 service implementation."""

# ruff: noqa: PLR5501 (use elif instead of if) - The code matches the spec
# better when written this way
from __future__ import annotations

import threading
from collections import deque
from queue import Empty, SimpleQueue
from typing import TYPE_CHECKING

from spacepackets.uslp import BypassSequenceControlFlag, ProtocolCommandFlag

from ..common.fsm import StateMachine, TransitionTo
from ..common.service import CopService
from ..common.util import logger
from ._fop1_events import FopEvent
from .transitions import _transitions
from .types import (
    AbortRequest,
    Alert,
    AsyncNotification,
    AsyncNotificationType,
    DirectiveNotification,
    DirectiveRequest,
    DirectiveType,
    FopInterface,
    FopState,
    NotificationType,
    RequestToTransferFdu,
    Response,
    ResponseType,
    SentQueueEntry,
    ServiceType,
    TransferNotification,
    TransmitRequestForFrame,
    WaitQueueEntry,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..common.ccsds import ControlWord, Gvcid


class Fop1(CopService):
    """Frame Operation Procedure-1 (FOP-1), CCSDS 323.1-B-2.

    Attributes
    ----------
    interface
        The interface between FOP-1 and its Higher and Lower Procedures.
    v_s
        The Transmitter_Frame_Sequence_Number, usually denoted V(S).
    ad_out
        The AD_Out_Flag, for Type-AD Transfer Frames.
    bc_out
        The BC_Out_Flag, for Type-BC Transfer Frames.
    bd_out
        The BD_Out_Flag, for Type-BD Transfer Frames.
    nn_r
        The Expected_Acknowledgement_Frame_Sequence_Number
    timer_initial_value
        The initial value for the FOP timer, T1.
    transmission_limit
        The maximum number of times the first Transfer Frame on the Sent_Queue may be retransmitted.
    transmission_count
        Transmission_Count is used to count the number of transmissions of the first frame on the
        Sent_Queue.
    sliding_window_width
        K, the FOP sliding window with.
    timeout_type
        Timeout_Type specifies what action to perform when T1 times out and
        Transmission_Count == Transmission_Limit.
    suspend_state
        The last state FOP-1 was in when it was suspended. Usually denoted SS. When SS = 0, FOP-1 is
        not suspended.
    """

    def __init__(
        self,
        gvcid: Gvcid,
        k: int = 10,
        timer_initial_value: int = 3,
    ) -> None:
        """Initialize FOP-1.

        Parameters
        ----------
        gvcid
            The Global Virtual Channel Identifier (GVCID) for this service's channel.
        k
            The FOP_Sliding_Window_Width ('K').
        timer_initial_value
            The timer initial value (T1).
        """
        super().__init__()
        self.interface = FopInterface()
        self.v_s: int = 0
        self._wait_queue: WaitQueueEntry | None = None
        self._sent_queue: deque[SentQueueEntry] = deque()
        # True == Ready and False == Not_Ready
        self.ad_out: bool = False
        self.bd_out: bool = False
        self.bc_out: bool = False
        self.nn_r: int = 0
        self.timer_initial_value: int = timer_initial_value
        self.transmission_limit: int = 1
        self.transmission_count: int = 0
        self.sliding_window_width: int = 0
        self._set_window_width(k)
        self.timeout_type: int = 0
        self.suspend_state: int = 0

        self._timer: threading.Timer | None = None
        self._timer_events: SimpleQueue = SimpleQueue()
        self._request_id: int = 0
        self._gvcid: Gvcid = gvcid
        self._pending_directive_request: DirectiveRequest | None = None
        self._pending_fdu: RequestToTransferFdu | None = None

        self._fsm = StateMachine[FopState, FopEvent](FopState.INITIAL)
        for tr_from, tr_to in _transitions.items():
            state, action_strs = tr_to
            actions = [getattr(self, name) for name in action_strs]
            self._fsm.add_transition(tr_from, TransitionTo(state, actions))

    @property
    def state(self) -> FopState:
        """Get the state of FOP-1's state machine.

        Returns
        -------
        FopState
            The current state of FOP-1.
        """
        return self._fsm.current_state

    def on_clcw_arrived(self, clcw: ControlWord) -> None:
        """Signal FOP-1 that a CLCW (control word) has arrived for this service.

        clcw
            The control word.
        """
        if not self._validate_clcw(clcw):
            self._on_event(FopEvent.E15)
            return
        if clcw.lockout:
            self._on_event(FopEvent.E14)
        else:
            if clcw.report_value == self.v_s:
                # valid N(R) and all outstanding Type-AD acked
                if clcw.retransmit:
                    self._on_event(FopEvent.E4)
                else:
                    if clcw.wait:
                        self._on_event(FopEvent.E3)
                    else:
                        if clcw.report_value == self.nn_r:
                            # no new frames acked
                            self._on_event(FopEvent.E1)
                        else:
                            # some new frames acked
                            self._on_event(FopEvent.E2)
            elif self.v_s > clcw.report_value >= self.nn_r:
                # valid N(R) and some outstanding AD not yet acked
                if clcw.retransmit:
                    if self.transmission_limit == 1:
                        if clcw.report_value == self.nn_r:
                            self._on_event(FopEvent.E102)
                        else:
                            self._on_event(FopEvent.E101)
                    elif self.transmission_limit > 1:
                        if clcw.report_value == self.nn_r:
                            if self.transmission_count < self.transmission_limit:
                                if clcw.wait:
                                    self._on_event(FopEvent.E11_B)
                                else:
                                    self._on_event(FopEvent.E10_B)
                            else:
                                if clcw.wait:
                                    self._on_event(FopEvent.E103)
                                else:
                                    self._on_event(FopEvent.E12_B)
                        else:
                            if clcw.wait:
                                self._on_event(FopEvent.E8_B)
                            else:
                                self._on_event(FopEvent.E9_B)
                    else:
                        logger.error("Transmission_Limit < 1")
                        self.transmission_limit = 1
                else:
                    if clcw.wait:
                        self._on_event(FopEvent.E7_B)
                    else:
                        if clcw.report_value == self.nn_r:
                            self._on_event(FopEvent.E5)
                        else:
                            self._on_event(FopEvent.E6_B)
            else:
                # invalid N(R)
                self._on_event(FopEvent.E13)

    def on_receive_request_to_transfer_fdu(self, request: RequestToTransferFdu) -> None:
        """Signal FOP-1 that a Request To Transfer FDU has arrived for this service.

        Parameters
        ----------
        request
            The Request To Transfer FDU signal.
        """
        self._pending_fdu = request
        if request.service_type == ServiceType.AD:
            if self._wait_queue is None:
                self._on_event(FopEvent.E19)
            else:
                self._on_event(FopEvent.E20)
        elif request.service_type == ServiceType.BD:
            if self.bd_out:
                self._on_event(FopEvent.E21_B)
            else:
                self._on_event(FopEvent.E22)

    def on_receive_directive(self, directive: DirectiveRequest) -> None:
        """Signal FOP-1 that a Directive Request has been received for this service.

        Parameters
        ----------
        directive
            The Directive Request signal.
        """
        self._pending_directive_request = directive
        d_type = directive.directive_type
        if d_type is DirectiveType.INITIATE_AD_NO_CLCW:
            self._on_event(FopEvent.E23)
        elif d_type is DirectiveType.INITIATE_AD_WITH_CLCW:
            self._on_event(FopEvent.E24)
        elif d_type is DirectiveType.INITIATE_AD_WITH_UNLOCK:
            if self.bc_out:
                self._on_event(FopEvent.E25_B)
            else:
                self._on_event(FopEvent.E26)
        elif d_type is DirectiveType.INITIATE_AD_WITH_SET_V_R:
            if self.bc_out:
                self._on_event(FopEvent.E27_B)
            else:
                self._on_event(FopEvent.E28)
        elif d_type is DirectiveType.TERMINATE_AD:
            self._on_event(FopEvent.E29)
        elif d_type is DirectiveType.RESUME_AD:
            if self.suspend_state == 0:
                self._on_event(FopEvent.E30)
            elif self.suspend_state == 1:
                self._on_event(FopEvent.E31_B)
            elif self.suspend_state == 2:
                self._on_event(FopEvent.E32_B)
            elif self.suspend_state == 3:
                self._on_event(FopEvent.E33_B)
            elif self.suspend_state == 4:
                self._on_event(FopEvent.E34_B)
        elif d_type is DirectiveType.SET_V_S:
            self._on_event(FopEvent.E35_B)
        elif d_type is DirectiveType.SET_SLIDING_WINDOW_WIDTH:
            self._on_event(FopEvent.E36)
        elif d_type is DirectiveType.SET_T1:
            self._on_event(FopEvent.E37)
        elif d_type is DirectiveType.SET_TRANSMISSION_LIMIT:
            self._on_event(FopEvent.E38)
        elif d_type is DirectiveType.SET_TIMEOUT_TYPE:
            self._on_event(FopEvent.E39)
        else:
            self._on_event(FopEvent.E40)

    def on_receive_response_from_lower_layer(self, response: Response) -> None:
        """Signal to FOP-1 that a Response has been received from the lower layer.

        Parameters
        ----------
        response
            The Response from the lower layer.
        """
        if response.response_type == ResponseType.AD_ACCEPTED:
            self._on_event(FopEvent.E41)
        elif response.response_type == ResponseType.AD_REJECTED:
            self._on_event(FopEvent.E42)
        elif response.response_type == ResponseType.BC_ACCEPTED:
            self._on_event(FopEvent.E43)
        elif response.response_type == ResponseType.BC_REJECTED:
            self._on_event(FopEvent.E44)
        elif response.response_type == ResponseType.BD_ACCEPTED:
            self._on_event(FopEvent.E45)
        elif response.response_type == ResponseType.BD_REJECTED:
            self._on_event(FopEvent.E46)

    def _validate_clcw(self, clcw: ControlWord) -> bool:
        return clcw.cop_in_effect == 0b01 and clcw.vcid == self._gvcid.vcid

    def _on_event(self, event: FopEvent) -> None:
        logger.debug(f"Event received: {event}")
        self._fsm.process_event(event)
        # FDUs are always consumed or rejected within 1 event cycle
        self._pending_fdu = None

    def start_timer(self) -> None:
        """Start the timer, T1."""
        if self._timer is not None:
            self.cancel_timer()
        self._timer = threading.Timer(self.timer_initial_value, self._on_timer_expired)
        self._timer.start()

    def cancel_timer(self) -> None:
        """Cancel the timer."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer_events = SimpleQueue()

    def _on_timer_expired(self) -> None:
        if self.state == FopState.INITIAL:
            return
        self._timer_events.put_nowait(None)

    def drain_timer_events(self) -> None:
        """Drain and process events from the timer event queue.

        This should be run *after* event processing since a CLCW may arrive during processing.
        """
        try:
            while True:
                self._timer_events.get_nowait()
                if self.transmission_count < self.transmission_limit:
                    if self.timeout_type == 0:
                        self._on_event(FopEvent.E16_B)
                    elif self.timeout_type == 1:
                        self._on_event(FopEvent.E104)
                    else:
                        logger.error("Timeout_Type not 0 or 1, resetting to 0")
                        self.timeout_type = 0
                else:
                    if self.timeout_type == 0:
                        self._on_event(FopEvent.E17_B)
                    elif self.timeout_type == 1:
                        self._on_event(FopEvent.E18_B)
                    else:
                        logger.error("Timeout_Type not 0 or 1, resetting to 0")
                        self.timeout_type = 0
        except Empty:
            return

    def accept_fdu(self) -> None:
        """Execute the 'ACCEPT' action, for FDUs."""
        self._respond_to_fdu(NotificationType.ACCEPT)

    def reject_fdu(self) -> None:
        """Execute the 'REJECT' action, for FDUs."""
        self._respond_to_fdu(NotificationType.REJECT)

    def _respond_to_fdu(self, n_t: NotificationType) -> None:
        if self._pending_fdu is None:
            raise RuntimeError("called without pending fdu")
        self.interface.to_higher.try_appendleft(
            TransferNotification(
                gvcid=self._pending_fdu.gvcid,
                request_id=self._pending_fdu.request_id,
                notification_type=n_t,
            )
        )

    def alert(self, alert_type: Alert) -> None:
        """Execute the 'ALERT' action."""
        logger.debug(f"Alert received: {alert_type}")
        self.cancel_timer()
        self._sent_queue.clear()
        self._wait_queue = None
        if (
            self._pending_directive_request is not None
            and self._pending_directive_request.directive_type
            in (
                DirectiveType.INITIATE_AD_NO_CLCW,
                DirectiveType.INITIATE_AD_WITH_CLCW,
                DirectiveType.INITIATE_AD_WITH_UNLOCK,
                DirectiveType.INITIATE_AD_WITH_SET_V_R,
            )
        ):
            self._respond_to_directive(NotificationType.NEGATIVE_CONFIRM)
            self._pending_directive_request = None
        self.interface.to_higher.try_appendleft(
            AsyncNotification(self._gvcid, AsyncNotificationType.ALERT, alert_type)
        )

    def suspend(self) -> None:
        """Execute the 'SUSPEND' action. Suspend FOP and notify the Higher Procedures.

        This is a parameterless state machine event.
        """
        self.suspend_state = self.state.value
        self.interface.to_higher.try_appendleft(
            AsyncNotification(self._gvcid, AsyncNotificationType.SUSPEND, None)
        )

    def set_k(self) -> None:
        """Set the FOP_Sliding_window_Width, K.

        This is a parameterless state machine event.
        """
        if self._pending_directive_request:
            try:
                self._set_window_width(self._pending_directive_request.directive_qualifier)
            except ValueError:
                logger.exception(
                    "Invalid Set FOP_SLIDING_WINDOW_WIDTH directive (K=%d)",
                    self._pending_directive_request.directive_qualifier,
                )
        else:
            logger.error("Missing DirectiveRequest")

    def _set_window_width(self, k: int) -> None:
        if 1 <= k < 256:
            self.sliding_window_width = k
        else:
            raise ValueError(f"Invalid sliding window width K={k}")

    def set_t1_initial(self) -> None:
        """Set T1's initial value.

        This is a parameterless state machine event.
        """
        if self._pending_directive_request:
            self.timer_initial_value = self._pending_directive_request.directive_qualifier
        else:
            logger.error("Missing DirectiveRequest")

    def set_transmission_limit(self) -> None:
        """Set the FOP-1 transmission limit.

        This is a parameterless state machine event.
        """
        if self._pending_directive_request:
            self.transmission_limit = self._pending_directive_request.directive_qualifier
        else:
            logger.error("Missing DirectiveRequest")

    def set_tt(self) -> None:
        """Set the Timeout Type.

        This is a parameterless state machine event.
        """
        if self._pending_directive_request:
            self.timeout_type = self._pending_directive_request.directive_qualifier
        else:
            logger.error("Missing DirectiveRequest")

    def remove_acknowledged_frames_from_sent_queue(self) -> None:
        """Execute the 'Remove Acknowledged Frames from Sent Queue' action.

        This is a parameterless state machine event.
        """
        entries = list(self._sent_queue)
        self._sent_queue.clear()
        for entry in entries:
            notif = TransferNotification(
                entry.gvcid, entry.request_id, NotificationType.POSITIVE_CONFIRM
            )
            self.interface.to_higher.try_appendleft(notif)
            self.nn_r = (self.nn_r + 1) & 0xFF
        self.transmission_count = 1

    def initiate_retransmission(self) -> None:
        """Execute the 'Initiate Retransmission' action.

        This is a parameterless state machine event.
        """
        self.interface.to_lower.try_appendleft(AbortRequest(self._gvcid))
        self.transmission_count += 1
        self.start_timer()
        for entry in self._sent_queue:
            entry.to_be_retransmitted = True

    def look_for_directive(self) -> None:
        """Execute the 'Look For Directive' action.

        This is a parameterless state machine event.
        """
        if self.bc_out:
            entry = self._sent_queue[0]
            if entry.to_be_retransmitted:
                self.bc_out = False
                self.interface.to_lower.try_appendleft(
                    TransmitRequestForFrame(
                        entry.gvcid,
                        BypassSequenceControlFlag.EXPEDITED_QOS,
                        ProtocolCommandFlag.PROTOCOL_INFORMATION,
                        entry.n_s,
                        entry.tfdf,
                    )
                )

    def look_for_fdu(self) -> None:
        """Execute the 'Look For FDU' action.

        This is a parameterless state machine event.
        """
        if self.ad_out:
            result = next((entry for entry in self._sent_queue if entry.to_be_retransmitted), None)
            if result is not None:
                self.ad_out = False
                self.interface.to_lower.try_appendleft(
                    TransmitRequestForFrame(
                        result.gvcid,
                        BypassSequenceControlFlag.SEQ_CTRLD_QOS,
                        ProtocolCommandFlag.USER_DATA,
                        result.n_s,
                        result.tfdf,
                    )
                )
                result.to_be_retransmitted = False
            elif self.v_s < self.nn_r + self.sliding_window_width:
                if self._wait_queue is not None and self._wait_queue.service_type == ServiceType.AD:
                    waiting_fdu = self._wait_queue
                    self._wait_queue = None
                    self.interface.to_higher.try_appendleft(
                        TransferNotification(
                            waiting_fdu.gvcid, waiting_fdu.request_id, NotificationType.ACCEPT
                        )
                    )
                    self.transmit_type_ad_frame(waiting_fdu)

    def release_copy_of_bc_frame(self) -> None:
        """Release copy of type BC frame.

        This action is not defined in the COP-1 standard, instead it must be inferred
        from the context of the state machine. It is analogous to Remove acknowledged frames from
        Sent_Queue, in that is meant to "release" (purge or remove) the one BC frame that is in the
        Sent_Queue during S5.
        """
        self._sent_queue.clear()

    def accept_directive(self) -> None:
        """Execute the 'Accept' action, for directives.

        This is a parameterless state machine event.
        """
        self._respond_to_directive(NotificationType.ACCEPT)

    def confirm_directive(self) -> None:
        """Execute the 'Confirm' action, for directives.

        This is a parameterless state machine event.
        """
        self._respond_to_directive(NotificationType.POSITIVE_CONFIRM)
        self._pending_directive_request = None

    def reject_directive(self) -> None:
        """Execute 'Reject' action, for directives.

        This is a parameterless state machine event.
        """
        self._respond_to_directive(NotificationType.REJECT)
        self._pending_directive_request = None

    def _respond_to_directive(self, n_t: NotificationType) -> None:
        if self._pending_directive_request is None:
            raise RuntimeError("called without pending directive")
        self.interface.to_higher.try_appendleft(
            DirectiveNotification(
                self._pending_directive_request.gvcid,
                self._pending_directive_request.request_id,
                n_t,
            )
        )

    def initialize(self) -> None:
        """Execute the 'Initialize' action.

        This is a parameterless state machine event.
        """
        self._sent_queue.clear()
        self._wait_queue = None
        self.transmission_count = 1
        self.suspend_state = 0

    def resume(self) -> None:
        """Execute the 'Resume' action.

        This is a parameterless state machine event.
        """
        self.start_timer()
        self.suspend_state = 0

    def set_pending_v_r(self) -> None:
        """Execute the 'Set V(R)' action for AD service initialization.

        This is a parameterless state machine event.
        """
        value = (
            self._pending_directive_request.directive_qualifier
            if self._pending_directive_request
            else 0
        )
        self.v_s = self.nn_r = value

    def _gated_set_v_s_(self) -> None:
        if self.suspend_state == 0:
            self.accept_directive()
            self.set_pending_v_r()
            self.confirm_directive()

    def _ready_ad(self) -> None:
        self.ad_out = True

    def _ready_bc(self) -> None:
        self.bc_out = True

    def _ready_bd(self) -> None:
        self.bd_out = True

    def transmit_type_ad_frame(self, entry: WaitQueueEntry) -> None:
        """Execute the 'Transmit Type-AD Frame' action.

        This is only used within another action ('Look For FDU').

        Parameters
        ----------
        entry
            The Wait_Queue entry to send.
        """
        n_s = self.v_s
        sent_entry = SentQueueEntry(entry.request_id, entry.gvcid, entry.fdu, n_s)
        self.v_s = (self.v_s + 1) & 0xFF
        if len(self._sent_queue) == 0:
            self.transmission_count = 1
        self._sent_queue.append(sent_entry)
        self.start_timer()
        self.ad_out = False
        self.interface.to_lower.try_appendleft(
            TransmitRequestForFrame(
                gvcid=entry.gvcid,
                bypass_flag=BypassSequenceControlFlag.SEQ_CTRLD_QOS,
                command_flag=ProtocolCommandFlag.USER_DATA,
                v_s=n_s,
                tfdf=entry.fdu,
            )
        )

    def transmit_type_bd_frame(self) -> None:
        """Execute the 'Transmit Type-BD Frame' action.

        This is a parameterless state machine event.
        """
        if self._pending_fdu is None:
            logger.error("Transmit BD called without pending FDU")
            return
        self.bd_out = False
        self.interface.to_lower.try_appendleft(
            TransmitRequestForFrame(
                gvcid=self._gvcid,
                bypass_flag=BypassSequenceControlFlag.EXPEDITED_QOS,
                command_flag=ProtocolCommandFlag.USER_DATA,
                v_s=0,  # seq num not applicable for BD
                tfdf=self._pending_fdu.fdu,
            )
        )

    def transmit_unlock_bc_frame(self) -> None:
        """Execute the 'Transmit Unlock Type-BC Frame' action.

        This is a parameterless state machine event.
        """
        self.bd_out = False
        self.interface.to_lower.try_appendleft(
            TransmitRequestForFrame(
                gvcid=self._gvcid,
                bypass_flag=BypassSequenceControlFlag.EXPEDITED_QOS,
                command_flag=ProtocolCommandFlag.PROTOCOL_INFORMATION,
                v_s=0,
                tfdf=b"\x00",
            )
        )

    def transmit_set_v_r_bc_frame(self) -> None:
        """Execute the 'Transmit Set V(R) Type-BC Frame' action.

        This is a parameterless state machine event.
        """
        if not self._pending_directive_request:
            logger.error("Missing Directive Request")
            return
        self.bc_out = False
        self.interface.to_lower.try_appendleft(
            TransmitRequestForFrame(
                gvcid=self._pending_directive_request.gvcid,
                bypass_flag=BypassSequenceControlFlag.EXPEDITED_QOS,
                command_flag=ProtocolCommandFlag.PROTOCOL_INFORMATION,
                v_s=0,
                tfdf=bytes(
                    [0x82, 0x00, self._pending_directive_request.directive_qualifier],
                ),
            )
        )

    def add_to_wait_queue(self) -> None:
        """Execute the 'Add to Wait_Queue' action.

        This is a parameterless state machine event.
        """
        if self._pending_fdu is None:
            raise RuntimeError("called without pending fdu")
        self._wait_queue = WaitQueueEntry(
            request_id=self._pending_fdu.request_id,
            gvcid=self._pending_fdu.gvcid,
            fdu=self._pending_fdu.fdu,
            service_type=self._pending_fdu.service_type,
        )
        self._pending_fdu = None


# generate methods for alerts since transitions are parameterless
for at in Alert:

    def make_alert(alert_type: Alert) -> Callable[[Fop1], None]:
        """Create the alert function.

        Parameters
        ----------
        alert_type
            The type of the alert.
        """

        def action(self: Fop1) -> None:
            self.alert(alert_type)

        return action

    setattr(Fop1, f"_alert_{at.name}", make_alert(at))
