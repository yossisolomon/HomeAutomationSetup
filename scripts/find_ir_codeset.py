"""Standalone IR code-set finder. Deps: python-broadlink + stdlib (jq optional).

Capture an unknown AC's IR 'off' from its real remote, match it against the
ar_smart_ir climate code-set DB, and report manufacturer/model/device_code.

Usage:
  python3 scripts/find_ir_codeset.py --device-ip 192.168.1.19
  python3 scripts/find_ir_codeset.py --discover
  python3 scripts/find_ir_codeset.py --device-ip 192.168.1.18 --refresh-db
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import time
from collections import Counter

try:
    from scripts import ir_codec, ir_match
except ImportError:  # run standalone: python scripts/find_ir_codeset.py
    import ir_codec
    import ir_match


def clean_captures(captures: list[list[int]]) -> list[int]:
    if not captures:
        raise ValueError("no captures provided")
    if len(captures) == 1:
        return list(captures[0])
    counts = Counter(len(c) for c in captures)
    modal_len, _ = counts.most_common(1)[0]
    keep = [c for c in captures if len(c) == modal_len]
    if len(keep) < 2:
        raise ValueError(
            f"inconsistent captures (pulse counts {[len(c) for c in captures]}); "
            "re-capture — likely bad reception or wrong button"
        )
    return [int(statistics.median(col)) for col in zip(*keep)]


def format_report(entry: dict, match_score: float, confirmed: bool) -> str:
    tag = "replay-confirmed" if confirmed else "unconfirmed"
    models = ", ".join(entry.get("models") or []) or "?"
    return (
        f"MATCH ({match_score:.0f}%, {tag}):\n"
        f"  manufacturer : {entry.get('manufacturer', '?')}\n"
        f"  model        : {models}\n"
        f"  device_code  : {entry.get('device_code', '?')}\n"
    )


REPO_URL = "https://github.com/marsh4200/ar_smart_ir"
DEFAULT_DB_DIR = "/tmp/ar_smart_ir_db"
CLIMATE_GLOB = "custom_components/ar_smart_ir/codes/climate"


def ensure_db(db_dir: str, refresh: bool) -> str:
    """Clone (sparse) the code-set repo if missing; pull if --refresh-db."""
    if not os.path.isdir(os.path.join(db_dir, ".git")):
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--sparse", REPO_URL, db_dir],
            check=True,
        )
        subprocess.run(
            ["git", "-C", db_dir, "sparse-checkout", "set",
             "custom_components/ar_smart_ir/codes/climate"],
            check=True,
        )
    elif refresh:
        subprocess.run(["git", "-C", db_dir, "pull", "--ff-only"], check=True)
    return db_dir


def build_mini_db(db_dir: str, force: bool = False) -> str:
    """Reduce codes/climate/*.json to a compact mini_db.ndjson cache."""
    climate = os.path.join(db_dir, CLIMATE_GLOB)
    mini = os.path.join(db_dir, "mini_db.ndjson")
    if os.path.exists(mini) and not force:
        return mini
    if shutil.which("jq"):
        jq = (
            '{device_code:(input_filename|gsub(".*/";"")|gsub(".json$";"")), '
            "manufacturer, models:.supportedModels, enc:.commandsEncoding, off:.commands.off}"
        )
        nproc = str(os.cpu_count() or 4)
        with open(mini, "w", encoding="utf-8") as out:
            find = subprocess.Popen(
                ["find", climate, "-name", "*.json", "-print0"], stdout=subprocess.PIPE
            )
            subprocess.run(
                ["xargs", "-0", "-P", nproc, "-I", "{}", "jq", "-c", jq, "{}"],
                stdin=find.stdout, stdout=out, check=True,
            )
            find.stdout.close()
            find.wait()
    else:
        with open(mini, "w", encoding="utf-8") as out:
            for name in sorted(os.listdir(climate)):
                if not name.endswith(".json"):
                    continue
                with open(os.path.join(climate, name), encoding="utf-8") as fh:
                    d = json.load(fh)
                out.write(json.dumps({
                    "device_code": name[:-5],
                    "manufacturer": d.get("manufacturer"),
                    "models": d.get("supportedModels"),
                    "enc": d.get("commandsEncoding"),
                    "off": d.get("commands", {}).get("off"),
                }, ensure_ascii=False) + "\n")
    return mini


LEARN_POLL_TIMEOUT = 30


def connect_device(ip: str | None, discover: bool, timeout: int):
    import broadlink
    if discover and not ip:
        devices = broadlink.discover(timeout=timeout)
        if not devices:
            raise SystemExit("no broadlink devices found on the LAN")
        dev = devices[0]
        print(f"Discovered {dev.type} at {dev.host[0]}")
    elif ip:
        dev = broadlink.hello(ip)
    else:
        raise SystemExit("provide --device-ip <ip> or --discover")
    dev.auth()
    return dev


def capture_once(dev, timeout: int) -> list[int]:
    import broadlink.exceptions
    dev.enter_learning()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.4)
        try:
            data = dev.check_data()
        except broadlink.exceptions.StorageError:
            continue
        return ir_codec.decode_broadlink_bytes(data)
    raise TimeoutError("no IR packet received")


def capture(dev, label: str, n: int, timeout: int) -> list[int]:
    while True:
        caps = []
        for k in range(n):
            print(f"  Press {label} ({k + 1}/{n}) within {timeout}s ...")
            try:
                caps.append(capture_once(dev, timeout))
            except TimeoutError:
                print("  timeout — retrying this press")
        if not caps:
            if input("  all presses timed out — retry? [y/N]: ").strip().lower() != "y":
                raise SystemExit("aborted by user")
            continue
        try:
            return clean_captures(caps)
        except ValueError as err:
            print(f"  {err}")
            if input("  re-capture this command? [Y/n]: ").strip().lower() == "n":
                raise SystemExit("aborted by user")


def replay(dev, entry: dict) -> None:
    off = entry["off"]
    payload = (
        ir_codec.b64_to_bytes(off)
        if (entry.get("enc") or "").lower() == "base64"
        else ir_codec.encode_broadlink(ir_codec.raw_to_ticks(off))
    )
    dev.send_data(payload)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Identify an AC's ar_smart_ir code-set from its IR remote.")
    p.add_argument("--device-ip", help="Broadlink device IP")
    p.add_argument("--discover", action="store_true", help="Scan the LAN for a Broadlink device")
    p.add_argument("--db-dir", default=DEFAULT_DB_DIR, help=f"code-set checkout dir (default {DEFAULT_DB_DIR})")
    p.add_argument("--refresh-db", action="store_true", help="git pull the code-set DB to latest")
    p.add_argument("--captures", type=int, default=3, help="captures per command (default 3)")
    p.add_argument("--timeout", type=int, default=LEARN_POLL_TIMEOUT, help="per-capture timeout seconds (also used as the --discover scan duration)")
    p.add_argument("--top", type=int, default=5, help="shortlist size to show/confirm")
    p.add_argument("--controller", default="remote.<your_broadlink_entity>", help="HA remote entity for the report")
    args = p.parse_args(argv)

    db = ensure_db(args.db_dir, args.refresh_db)
    mini = build_mini_db(db, force=args.refresh_db)
    entries = ir_match.load_mini_db(mini)
    print(f"Loaded {len(entries)} code-sets from {mini}")

    dev = connect_device(args.device_ip, args.discover, args.timeout)
    print("Capturing OFF from the real remote:")
    ref = capture(dev, "OFF", args.captures, args.timeout)

    ranked = ir_match.rank(ref, entries)
    if not ranked or ranked[0]["score"] == 0.0:
        print("No candidate matched. Try --refresh-db or a cleaner capture.")
        return 1

    if ir_match.is_tie(ranked):
        print("Top candidates tie on OFF — capturing a 2nd command to disambiguate.")
        print("Set the remote to COOL, a fixed temperature, and a fixed fan speed, then send it.")
        ref2 = capture(dev, "COOL/<temp>/<fan>", args.captures, args.timeout)
        shortlist = ranked[: args.top]
        for entry in shortlist:
            full = _load_full_codeset(db, entry["device_code"])
            cand2 = _extract_cool_command(full)
            entry["score2"] = ir_match.score(ref2, cand2) if cand2 else 0.0
        shortlist.sort(key=lambda e: (e["score"] + e.get("score2", 0.0)), reverse=True)
        # tail (beyond --top) keeps its score-only order and is never re-ranked;
        # the replay-confirm loop is bounded by --top, so only the re-scored
        # shortlist is ever surfaced for confirmation.
        ranked = shortlist + ranked[args.top:]

    print("\nTop candidates:")
    for e in ranked[: args.top]:
        print(f"  {e['score']:5.1f}%  code {e['device_code']:>5}  "
              f"{e.get('manufacturer','?')}  {', '.join(e.get('models') or []) or '?'}")

    confirmed = None
    for entry in ranked[: args.top]:
        print(f"\nReplaying OFF for code {entry['device_code']} ({entry.get('manufacturer','?')}).")
        try:
            replay(dev, entry)
        except Exception as err:  # noqa: BLE001 - report and continue to next candidate
            print(f"  replay failed: {err}")
            continue
        if input("  Did the AC react? [y/N]: ").strip().lower() == "y":
            confirmed = entry
            break

    chosen = confirmed or ranked[0]
    reported = chosen["score"] + chosen.get("score2", 0.0)
    print("\n" + format_report(chosen, reported, confirmed is not None))
    print(f"→ ar_smart_ir → Climate → manufacturer "
          f"\"{chosen.get('manufacturer','?')}\" → that model")
    print(f"→ controller entity: {args.controller}")
    return 0


def _load_full_codeset(db_dir: str, device_code: str) -> dict:
    with open(os.path.join(db_dir, CLIMATE_GLOB, f"{device_code}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _extract_cool_command(full: dict):
    """Best-effort: first cool command found, decoded to ticks. None if absent."""
    cool = (full.get("commands") or {}).get("cool")
    if not isinstance(cool, dict):
        return None
    enc = (full.get("commandsEncoding") or "").lower()
    for fan in cool.values():
        if isinstance(fan, dict):
            for cmd in fan.values():
                if isinstance(cmd, str):
                    try:
                        return (ir_codec.decode_broadlink_b64(cmd) if enc == "base64"
                                else ir_codec.raw_to_ticks(cmd))
                    except (ValueError, TypeError):
                        return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
