import base64

import pytest
from scripts import find_ir_codeset as f
from scripts import ir_codec


def _b64(ticks):
    return base64.b64encode(ir_codec.encode_broadlink(ticks)).decode()


def test_clean_captures_medians_agreeing():
    caps = [[100, 200, 50], [110, 190, 52], [90, 210, 48]]
    assert f.clean_captures(caps) == [100, 200, 50]


def test_clean_captures_drops_outlier_length():
    caps = [[100, 200, 50], [110, 190, 52], [1, 2]]  # last has wrong count
    assert f.clean_captures(caps) == [105, 195, 51]  # median of the two 3-length


def test_clean_captures_raises_when_all_disagree():
    with pytest.raises(ValueError):
        f.clean_captures([[1, 2], [1, 2, 3], [1, 2, 3, 4]])


def test_clean_captures_single_capture_ok():
    assert f.clean_captures([[100, 200, 50]]) == [100, 200, 50]


def test_format_report_confirmed():
    entry = {"manufacturer": "Tornado", "models": ["RGS-XYZ"], "device_code": "1234"}
    out = f.format_report(entry, 94.0, confirmed=True)
    assert "MATCH (94%, replay-confirmed)" in out
    assert "Tornado" in out and "RGS-XYZ" in out and "1234" in out


TEMP_TICKS = [10, 20, 30, 40]
JUNK_TICKS = [99, 98, 97, 96]


def test_extract_cool_flat_temp():
    # 2460-like: cool -> fan -> temp
    full = {"commandsEncoding": "Base64",
            "commands": {"cool": {"high": {"23": _b64(TEMP_TICKS)}}}}
    assert f._extract_cool_command(full) == TEMP_TICKS


def test_extract_cool_swing_nested_temp():
    # 1622/1705-like: cool -> fan -> swing_state -> temp (old code missed this)
    full = {"commandsEncoding": "Base64",
            "commands": {"cool": {"high": {"vSwing": {"23": _b64(TEMP_TICKS)}}}}}
    assert f._extract_cool_command(full) == TEMP_TICKS


def test_extract_cool_prefers_temp_over_non_temp_leaf():
    # a non-temp leaf (e.g. a swing toggle) must not win over a real temp leaf
    full = {"commandsEncoding": "Base64",
            "commands": {"cool": {"high": {"swing": _b64(JUNK_TICKS),
                                           "23": _b64(TEMP_TICKS)}}}}
    assert f._extract_cool_command(full) == TEMP_TICKS


def test_extract_cool_falls_back_to_any_leaf_without_temps():
    full = {"commandsEncoding": "Base64",
            "commands": {"cool": {"high": {"swing": _b64(JUNK_TICKS)}}}}
    assert f._extract_cool_command(full) == JUNK_TICKS


def test_extract_cool_none_when_absent():
    assert f._extract_cool_command({"commands": {"off": "x"}}) is None
