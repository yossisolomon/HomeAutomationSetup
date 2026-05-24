#!/usr/bin/env python3
"""
Learn RF codes directly from RM4 Pro — no broadlinkmanager needed.

Passes frequency directly to find_rf_packet() — no sweep required.
Saves to scripts/rf_codes_cache.json (accumulates — safe to re-run/resume).
Fan and command definitions loaded from scripts/fans.json.

Usage (run ON blacky):
  python3 scripts/learn_rf_codes.py              # learn all missing codes
  python3 scripts/learn_rf_codes.py --relearn    # re-learn all codes (overwrite)
  python3 scripts/learn_rf_codes.py --fan NAME   # only codes for one fan
  python3 scripts/learn_rf_codes.py --cmd CMD    # only one command (implies --relearn)
  python3 scripts/learn_rf_codes.py --freq 315   # use 315MHz instead of 433.92

After learning, run:
  python3 scripts/sync_rf_codes.py --cache-only --restart
"""
import argparse
import base64
import json
import pathlib
import sys
import time

try:
    import broadlink
    import broadlink.exceptions
except ImportError:
    sys.exit("pip install broadlink")

REPO_ROOT    = pathlib.Path(__file__).parent.parent
CACHE_FILE   = REPO_ROOT / "scripts" / "rf_codes_cache.json"
FANS_FILE    = REPO_ROOT / "scripts" / "fans.json"
DEVICE_IP    = "192.168.1.18"
DEFAULT_FREQ = 433.92
LEARN_TIMEOUT = 12


def load_fans():
    cfg = json.loads(FANS_FILE.read_text())
    return cfg["fans"], cfg["types"]


def learn_one(dev, key, frequency):
    print(f"  Press button ONCE (up to {LEARN_TIMEOUT}s)...")
    dev.find_rf_packet(frequency=frequency)
    deadline = time.time() + LEARN_TIMEOUT
    while time.time() < deadline:
        print(f"  {deadline - time.time():.0f}s ", end="\r", flush=True)
        time.sleep(0.5)
        try:
            data = dev.check_data()
            if len(data) != 250:
                print(f"  BAD ({len(data)} bytes — expected 250) retrying...")
                return None
            b64 = base64.b64encode(data).decode()
            print(f"  OK ({len(data)} bytes)        ")
            return b64
        except broadlink.exceptions.StorageError:
            continue
    print("  TIMEOUT — no code received")
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--relearn", action="store_true", help="Re-learn all codes (overwrite existing)")
    p.add_argument("--fan",     default=None,        help="Only learn codes for this fan id (e.g. fan_yossis_office)")
    p.add_argument("--cmd",     default=None,        help="Only learn this one command (implies --relearn for that key)")
    p.add_argument("--freq",    type=float, default=DEFAULT_FREQ, help=f"RF frequency in MHz (default: {DEFAULT_FREQ})")
    args = p.parse_args()

    fans, types = load_fans()
    codes = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    print(f"Cache: {len(codes)} codes loaded from {CACHE_FILE}")

    if args.fan:
        fans = [f for f in fans if f["id"] == args.fan]
        if not fans:
            sys.exit(f"Fan '{args.fan}' not found in fans.json")

    print(f"Connecting to RM4 Pro at {DEVICE_IP}...")
    dev = broadlink.hello(DEVICE_IP)
    dev.auth()
    print(f"Auth ok. Frequency: {args.freq} MHz")

    learned = 0
    skipped = 0

    for fan in fans:
        dev_id = fan["id"]
        cmds   = types[fan["type"]]["commands"]
        print(f"\n{'='*50}")
        print(f"FAN: {fan['name']} ({dev_id})")
        print(f"{'='*50}")
        for cmd in cmds:
            if args.cmd and cmd != args.cmd:
                continue
            key = f"{dev_id}/{cmd}"
            if key in codes and not args.relearn and not args.cmd:
                print(f"  [{cmd}] already learned — skipping")
                skipped += 1
                continue
            print(f"\n[{key}]")
            result = learn_one(dev, key, args.freq)
            if result:
                codes[key] = result
                CACHE_FILE.write_text(json.dumps(codes, indent=2, sort_keys=True))
                learned += 1
            else:
                try:
                    retry = input("  Retry? [y/N]: ").strip().lower()
                except EOFError:
                    retry = "n"
                if retry == "y":
                    result = learn_one(dev, key, args.freq)
                    if result:
                        codes[key] = result
                        CACHE_FILE.write_text(json.dumps(codes, indent=2, sort_keys=True))
                        learned += 1

    print(f"\n{'='*50}")
    print(f"Done. Learned: {learned}  Skipped: {skipped}  Total in cache: {len(codes)}")
    print(f"\nNext: python3 scripts/sync_rf_codes.py --cache-only --restart")


if __name__ == "__main__":
    main()
