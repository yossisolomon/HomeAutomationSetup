"""Pure matching: decode DB entries and score them against a reference. No I/O."""
import json

from scripts import ir_codec


def score(ref: list[int], cand: list[int], tol: float = 0.15, count_slack: int = 2) -> float:
    if not ref or not cand:
        return 0.0
    if abs(len(ref) - len(cand)) > count_slack:
        return 0.0
    n = min(len(ref), len(cand))
    hits = sum(1 for a, b in zip(ref[:n], cand[:n]) if abs(a - b) <= tol * max(a, b, 1))
    return 100.0 * hits / n


def entry_to_ticks(entry: dict) -> list[int] | None:
    off = entry.get("off")
    if not off:
        return None
    enc = (entry.get("enc") or "").lower()
    try:
        if enc == "base64":
            return ir_codec.decode_broadlink_b64(off)
        if enc == "raw":
            return ir_codec.raw_to_ticks(off)
    except (ValueError, TypeError):
        return None
    return None


def load_mini_db(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("off"):
                rows.append(row)
    return rows


def rank(ref: list[int], entries: list[dict], **kw) -> list[dict]:
    scored = []
    for entry in entries:
        cand = entry_to_ticks(entry)
        if cand is None:
            continue
        scored.append({**entry, "score": score(ref, cand, **kw)})
    scored.sort(key=lambda e: e["score"], reverse=True)
    return scored


def is_tie(ranked: list[dict], margin: float = 3.0) -> bool:
    return len(ranked) >= 2 and (ranked[0]["score"] - ranked[1]["score"]) < margin
