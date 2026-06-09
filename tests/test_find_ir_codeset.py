import pytest
from scripts import find_ir_codeset as f


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
