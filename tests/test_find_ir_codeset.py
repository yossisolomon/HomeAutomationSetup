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


def test_format_report_confirmed_off_only():
    entry = {"manufacturer": "Tornado", "models": ["RGS-XYZ"], "device_code": "1234"}
    out = f.format_report(entry, confirmed=True, off_score=94.0)
    assert "MATCH (OFF 94%, replay-confirmed)" in out
    assert "Tornado" in out and "RGS-XYZ" in out and "1234" in out


def test_format_report_unconfirmed():
    out = f.format_report({"device_code": "9"}, confirmed=False, off_score=90.0)
    assert "unconfirmed" in out


def test_format_score_off_only():
    assert f.format_score(90.4) == "OFF 90%"


def test_format_score_off_and_cool_not_summed():
    # the old bug summed these into a single >100% figure ("180%")
    s = f.format_score(90.4, 88.0)
    assert s == "OFF 90% + COOL 88%"
    assert "180" not in s and "178" not in s


def test_format_report_with_cool_shows_both_components():
    entry = {"manufacturer": "Chigo", "models": ["ZH/TY-01"], "device_code": "1581"}
    out = f.format_report(entry, confirmed=True, off_score=90.4, cool_score=90.0)
    assert "OFF 90% + COOL 90%" in out
    assert "180" not in out


def test_format_candidate_line_off_only():
    line = f.format_candidate_line({"score": 90.4, "device_code": "1581",
                                    "manufacturer": "Chigo", "models": ["ZH/TY-01"]})
    assert "OFF 90%" in line and "COOL" not in line and "1581" in line


def test_format_candidate_line_with_score2_not_summed():
    line = f.format_candidate_line({"score": 90.4, "score2": 88.0, "device_code": "2760",
                                    "manufacturer": "Tristar", "models": ["AC-5400"]})
    assert "OFF 90% + COOL 88%" in line and "180" not in line and "178" not in line


def test_format_off_table_lists_off_scores_only():
    ranked = [{"score": 90.4, "device_code": "1581", "manufacturer": "Chigo", "models": ["ZH/TY-01"]},
              {"score": 88.4, "device_code": "2760", "manufacturer": "Tristar", "models": ["AC-5400"]}]
    tbl = f.format_off_table(ranked, top=5)
    assert "OFF  90.4%" in tbl and "OFF  88.4%" in tbl
    assert "1581" in tbl and "2760" in tbl
    assert "COOL" not in tbl


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
