import base64

import pytest
from scripts import ir_codec

OFF_1000 = (
    "JgCSAAABKZEXNBgQFxEXEBc1FxAYEBcQGDQXERcQGDQXERcQFxEXEBcRFxAYEBcQGBAXNRcQ"
    "FxEXEBcRFxAYEBc1FxAXNRcQGBAXNRcQFwACjhcQGBAXEBgQFxEXEBcRFxAXERcQGBAXEBgQ"
    "FzQYEBcRFxAYEBcQGBAXEBgQFxEXEBcRFxAXERcQGBAXNBg0FxEXAA0FAAAAAAAA"
)


def test_decode_broadlink_b64_known_packet():
    pulses = ir_codec.decode_broadlink_b64(OFF_1000)
    assert len(pulses) == 140
    assert pulses[:12] == [297, 145, 23, 52, 24, 16, 23, 17, 23, 16, 23, 53]


def test_decode_rejects_non_ir_packet():
    rf = base64.b64encode(bytes([0xb2, 0x00, 0x02, 0x00, 0x10, 0x20])).decode()
    with pytest.raises(ValueError):
        ir_codec.decode_broadlink_b64(rf)


def test_decode_rejects_short_and_truncated_packets():
    # too short (< 4 bytes)
    with pytest.raises(ValueError):
        ir_codec.decode_broadlink_b64(base64.b64encode(bytes([0x26, 0x00])).decode())
    # declares 4-byte payload but a 0x00 escape runs past the end
    with pytest.raises(ValueError):
        ir_codec.decode_broadlink_b64(base64.b64encode(bytes([0x26, 0x00, 0x04, 0x00, 0x00, 0x01])).decode())


def test_encode_decode_round_trip():
    pulses = [297, 145, 23, 52, 300, 16, 70000 % 65536, 256, 1]
    out = ir_codec.encode_broadlink(pulses)
    assert out[0] == 0x26
    assert ir_codec.decode_broadlink_b64(__import__("base64").b64encode(out).decode()) == pulses


def test_raw_to_ticks_signed_us_string():
    ticks = ir_codec.raw_to_ticks("9040 -4410 650 -1590")
    assert ticks == [296, 145, 21, 52]


def test_raw_to_ticks_accepts_list():
    assert ir_codec.raw_to_ticks([9040, -4410]) == [296, 145]


def test_b64_to_bytes():
    assert ir_codec.b64_to_bytes("JgA=") == b"\x26\x00"


def test_decode_broadlink_bytes_matches_b64():
    import base64
    raw = base64.b64decode(OFF_1000)
    assert ir_codec.decode_broadlink_bytes(raw) == ir_codec.decode_broadlink_b64(OFF_1000)


def test_encode_skips_zero_ticks():
    # a 0-tick must not emit a bare 0x00 (which decode would misread as an escape)
    assert ir_codec.decode_broadlink_b64(__import__("base64").b64encode(ir_codec.encode_broadlink([100, 0, 200])).decode()) == [100, 200]
