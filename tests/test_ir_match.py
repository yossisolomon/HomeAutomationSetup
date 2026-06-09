import json

from scripts import ir_match


def test_score_identical_is_100():
    ref = [297, 145, 23, 52, 24]
    assert ir_match.score(ref, list(ref)) == 100.0


def test_score_jittered_within_tol_is_high():
    ref = [300, 150, 20, 50, 20]
    cand = [330, 165, 22, 45, 18]  # ~10% jitter, within default 15%
    assert ir_match.score(ref, cand) == 100.0


def test_score_count_mismatch_is_zero():
    assert ir_match.score([1, 2, 3], [1, 2, 3, 4, 5, 6]) == 0.0


def test_score_partial():
    ref = [100, 100, 100, 100]
    cand = [100, 100, 999, 999]  # 2 of 4 within tol
    assert ir_match.score(ref, cand) == 50.0


def test_entry_to_ticks_base64():
    entry = {"enc": "Base64", "off": "JgAGAAABKQEpAA0F"}
    ticks = ir_match.entry_to_ticks(entry)
    assert isinstance(ticks, list) and ticks  # decodes without error


def test_entry_to_ticks_raw():
    entry = {"enc": "Raw", "off": "9040 -4410"}
    assert ir_match.entry_to_ticks(entry) == [296, 145]


def test_entry_to_ticks_missing_off_returns_none():
    assert ir_match.entry_to_ticks({"enc": "Base64", "off": None}) is None


def test_entry_to_ticks_bad_base64_returns_none():
    assert ir_match.entry_to_ticks({"enc": "Base64", "off": "NOT_VALID_B64!!!"}) is None


# ── Task 6: mini-DB load, ranking, tie detection ──────────────────────────────

def _write_ndjson(tmp_path, rows):
    p = tmp_path / "mini_db.ndjson"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(p)


def test_load_mini_db_skips_blank_and_offless(tmp_path):
    path = _write_ndjson(tmp_path, [
        {"device_code": "1", "enc": "Raw", "off": "100 -100"},
        {"device_code": "2", "enc": "Raw", "off": None},
    ])
    rows = ir_match.load_mini_db(path)
    assert [r["device_code"] for r in rows] == ["1"]


def test_rank_orders_by_score(tmp_path):
    ref = [100, 100, 100, 100]
    entries = [
        # 3052 us ~= 100 ticks -> scores 100% vs ref; 30520 us ~= 1000 ticks -> rejected by tol
        {"device_code": "near", "enc": "Raw", "off": "3052 3052 3052 3052"},
        {"device_code": "far", "enc": "Raw", "off": "30520 30520 30520 30520"},
    ]
    ranked = ir_match.rank(ref, entries)
    assert ranked[0]["device_code"] == "near"
    assert ranked[0]["score"] >= ranked[1]["score"]


def test_is_tie_true_when_top_two_close():
    ranked = [{"score": 95.0}, {"score": 94.0}, {"score": 10.0}]
    assert ir_match.is_tie(ranked) is True


def test_is_tie_false_when_clear_winner():
    ranked = [{"score": 95.0}, {"score": 40.0}]
    assert ir_match.is_tie(ranked) is False
