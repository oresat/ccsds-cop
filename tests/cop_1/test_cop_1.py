import struct

import pytest
from spacepackets.uslp import (
    BypassSequenceControlFlag,
    PrimaryHeader,
    ProtocolCommandFlag,
    SourceOrDestField,
    TfdzConstructionRules,
    TransferFrame,
    TransferFrameDataField,
    TruncatedPrimaryHeader,
    UslpProtocolIdentifier,
)

from ccsds_cop.cop_1 import ControlWord, Gvcid
from ccsds_cop.cop_1.farm import (
    Farm1,
    FarmState,
    FduArrivedIndication,
    ValidFrameArrivedIndication,
)

# FIXME: Copied from oresat-c3-software, we'll eventually want to make these
# values more generic for this project? Specify a range to test over? Something.
TEST_VCID = 0
SPACECRAFT_ID = 0x4F53  # "OS" in ASCII
PRIMARY_HEADER_LEN = 7
SEQ_NUM_LEN = 4
DFH_LEN = 1
HMAC_LEN = 32
FECF_LEN = 2
TC_MIN_LEN = PRIMARY_HEADER_LEN + SEQ_NUM_LEN + DFH_LEN + HMAC_LEN + FECF_LEN


@pytest.fixture
def farm1() -> Farm1:
    return Farm1(w=254, allow_retransmission=True)


def make_test_frame(
    payload: bytes,
    prot_ident: UslpProtocolIdentifier,
    prot_ctrl: ProtocolCommandFlag,
    bypass_ctrl: BypassSequenceControlFlag,
) -> TransferFrame:
    # USLP transfer frame total length - 1
    frame_len = len(payload) + TC_MIN_LEN - 1
    return TransferFrame(
        header=PrimaryHeader(
            scid=SPACECRAFT_ID,
            map_id=0,
            vcid=TEST_VCID,
            src_dest=SourceOrDestField.DEST,
            frame_len=frame_len,
            vcf_count_len=2,
            vcf_count=0,
            op_ctrl_flag=False,
            prot_ctrl_cmd_flag=prot_ctrl,
            bypass_seq_ctrl_flag=bypass_ctrl,
        ),
        tfdf=TransferFrameDataField(
            tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
            uslp_ident=prot_ident,
            tfdz=payload,
        ),
    )


@pytest.fixture
def frame_type_bc() -> TransferFrame:
    payload_raw = b"\x82\x00\x05"  # set V(R) = 5
    return make_test_frame(
        payload_raw,
        UslpProtocolIdentifier.COP_1_CTRL_COMMANDS,
        ProtocolCommandFlag.PROTOCOL_INFORMATION,
        BypassSequenceControlFlag.EXPEDITED_QOS,
    )


@pytest.fixture
def frame_type_bd() -> TransferFrame:
    payload_raw = b"\x82\x00\x05"  # set V(R) = 5
    return make_test_frame(
        payload_raw,
        UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
        ProtocolCommandFlag.USER_DATA,
        BypassSequenceControlFlag.EXPEDITED_QOS,
    )


@pytest.fixture
def frame_type_ad() -> TransferFrame:
    payload_raw = b"\x82\x00\x05"  # set V(R) = 5
    return make_test_frame(
        payload_raw,
        UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
        ProtocolCommandFlag.USER_DATA,
        BypassSequenceControlFlag.SEQ_CTRLD_QOS,
    )


@pytest.fixture
def invalid_type_bc() -> TransferFrame:
    return make_test_frame(
        b"\x01",
        UslpProtocolIdentifier.COP_1_CTRL_COMMANDS,
        ProtocolCommandFlag.PROTOCOL_INFORMATION,
        BypassSequenceControlFlag.EXPEDITED_QOS,
    )


@pytest.fixture
def invalid_type_ac() -> TransferFrame:
    payload_raw = b"\x82\x00\x05"  # set V(R) = 5
    return make_test_frame(
        payload_raw,
        UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
        ProtocolCommandFlag.PROTOCOL_INFORMATION,
        BypassSequenceControlFlag.SEQ_CTRLD_QOS,
    )


@pytest.fixture
def invalid_seq_frame() -> TransferFrame:
    payload_raw = b"\x82\x00\x05"  # set V(R) = 5
    return make_test_frame(
        payload_raw,
        UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
        ProtocolCommandFlag.USER_DATA,
        BypassSequenceControlFlag.SEQ_CTRLD_QOS,
    )


class TestFarm1:
    def test_init(self) -> None:
        valid_w = 254
        valid_w_no_re = 256
        valid_pw = 256
        valid_nw = 0
        Farm1(valid_w, 0, 0, vcf_count_length=2, allow_retransmission=True)
        Farm1(valid_w_no_re, valid_pw, valid_nw, vcf_count_length=2, allow_retransmission=False)
        with pytest.raises(ValueError, match="2 <= W <= 254"):
            Farm1(500, 0, 0, vcf_count_length=2, allow_retransmission=True)
        with pytest.raises(ValueError, match="1 <= W <= 256"):
            Farm1(0, 0, 0, vcf_count_length=2, allow_retransmission=False)
        with pytest.raises(ValueError, match="1 <= PW <= 256"):
            Farm1(valid_w_no_re, 0, 0, vcf_count_length=2, allow_retransmission=False)
        with pytest.raises(ValueError, match="window must be positive"):
            Farm1(valid_w_no_re, valid_pw, -1, vcf_count_length=2, allow_retransmission=False)

    def test_process_bc(self, farm1: Farm1, frame_type_bc: TransferFrame) -> None:
        assert farm1._process_frame(frame_type_bc)
        assert farm1.b_counter == 1
        assert not farm1.retransmit
        assert farm1.v_r == 5
        assert farm1.state == FarmState.OPEN

    def test_process_invalid_bc(self, farm1: Farm1, invalid_type_bc: TransferFrame) -> None:
        assert not farm1._process_frame(invalid_type_bc)

    def test_process_bd(self, farm1: Farm1, frame_type_bd: TransferFrame) -> None:
        assert farm1._process_frame(frame_type_bd)
        indication = farm1.higher_interface.signal.pop()
        assert isinstance(indication, FduArrivedIndication)
        farm1.higher_interface.buffer.pop()

    def test_process_ad(self, farm1: Farm1, frame_type_ad: TransferFrame) -> None:
        assert farm1._process_frame(frame_type_ad)
        assert farm1.v_r == 1
        assert len(farm1.higher_interface.buffer) == 1

    def test_process_ac(self, farm1: Farm1, invalid_type_ac: TransferFrame) -> None:
        assert not farm1._process_frame(invalid_type_ac)

    def test_buffer_put(self, farm1: Farm1, frame_type_bc: TransferFrame) -> None:
        farm1.lower_interface.buffer.append(frame_type_bc)
        assert len(farm1.lower_interface.buffer) == 1

    def test_notify(self, farm1: Farm1, frame_type_bc: TransferFrame) -> None:
        gvcid = Gvcid(0b1100, frame_type_bc.header.scid, frame_type_bc.header.vcid)
        farm1.lower_interface.signal.append(ValidFrameArrivedIndication(gvcid))
        assert len(farm1.lower_interface.signal) == 1

    def test_trigger_retransmit(
        self, farm1: Farm1, frame_type_bc: TransferFrame, invalid_seq_frame: TransferFrame
    ) -> None:
        # set V(R) to predictable value first
        assert farm1._process_frame(frame_type_bc)
        invalid_ns = farm1.v_r + (farm1.v_r + farm1.positive_window_width - 1) // 2
        assert farm1.v_r < invalid_ns <= farm1.v_r + farm1.positive_window_width - 1, (
            "Failed to calculate invalid N(S) sequence number for this test"
        )
        assert not isinstance(invalid_seq_frame.header, TruncatedPrimaryHeader)
        invalid_seq_frame.header.vcf_count = invalid_ns
        assert not farm1._process_frame(invalid_seq_frame)
        assert farm1.retransmit

    def test_lockout(self, farm1: Farm1, invalid_seq_frame: TransferFrame) -> None:
        farm1.v_r = 0
        assert not isinstance(invalid_seq_frame.header, TruncatedPrimaryHeader)
        invalid_seq_frame.header.vcf_count = farm1.sliding_window_width // 2
        assert not farm1._process_frame(invalid_seq_frame)
        assert farm1.lockout

    def test_large_vcf(
        self, farm1: Farm1, frame_type_bc: TransferFrame, invalid_seq_frame: TransferFrame
    ) -> None:
        # weirdness may happen if modulo arithmetic is not respected
        # see the note under CCSDS 232.1-B-2 6.2.1 GENERAL
        # set V(R) to predictable value first
        assert farm1._process_frame(frame_type_bc)
        assert not isinstance(invalid_seq_frame.header, TruncatedPrimaryHeader)
        invalid_seq_frame.header.vcf_count = 60000
        assert not farm1._process_frame(invalid_seq_frame)


class TestClcw:
    def test_pack_length(self) -> None:
        assert len(ControlWord().pack()) == 4

    def test_default_roundtrip(self) -> None:
        clcw = ControlWord()
        assert ControlWord.unpack(clcw.pack()) == clcw

    def test_field_roundtrip(self) -> None:
        clcw = ControlWord(
            status_field=0b101,
            cop_in_effect=1,
            vcid=0x3F,
            no_rf_available=True,
            no_bit_lock=True,
            lockout=True,
            wait=True,
            retransmit=True,
            farm_b_counter=3,
            report_value=0xAB,
        )
        assert ControlWord.unpack(clcw.pack()) == clcw

    def test_reserved_spares_are_zero(self) -> None:
        # bits 16-17 and bit 8 must always be zero regardless of field values
        clcw = ControlWord(vcid=0x3F, report_value=0xFF)
        (word,) = struct.unpack(">I", clcw.pack())
        assert (word >> 16) & 0x3 == 0
        assert (word >> 8) & 0x1 == 0

    def test_flags_isolated(self) -> None:
        for attr, bit in [
            ("no_rf_available", 15),
            ("no_bit_lock", 14),
            ("lockout", 13),
            ("wait", 12),
            ("retransmit", 11),
        ]:
            clcw = ControlWord(**{attr: True})
            (word,) = struct.unpack(">I", clcw.pack())
            assert (word >> bit) & 0x1 == 1, f"{attr} not set at bit {bit}"
            other_flags = 0x1F & ~(1 << (bit - 11))
            assert (word >> 11) & other_flags == 0, f"extra flag bits set for {attr}"

    def test_unpack_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="CLCW requires 4 bytes"):
            ControlWord.unpack(b"\x00\x00\x00")

    def test_unpack_ignores_reserved_spare_bits(self) -> None:
        # reserved spare bits set in raw bytes should not bleed into named fields
        raw = struct.pack(">I", 0x0003_0100)  # spare bits 16-17 and bit 8 all set
        clcw = ControlWord.unpack(raw)
        assert clcw.report_value == 0
        assert not clcw.retransmit
