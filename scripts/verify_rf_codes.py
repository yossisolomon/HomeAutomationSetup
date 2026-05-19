#!/usr/bin/env python3
"""
Send learned RF codes directly to verify they work.
Fan definitions loaded from scripts/fans.json.

Usage (run ON blacky or locally with RM4 reachable):
  python3 scripts/verify_rf_codes.py                        # light toggle test on all fans
  python3 scripts/verify_rf_codes.py --fan fan_yossis_office
  python3 scripts/verify_rf_codes.py --fan fan_yossis_office --cmd fan_toggle
  python3 scripts/verify_rf_codes.py --fan fan_yossis_office --cmd light_toggle --times 2 --delay 5
"""
import argparse
import base64
import json
import pathlib
import sys
import time

try:
    import broadlink
except ImportError:
    sys.exit("pip install broadlink")

REPO_ROOT  = pathlib.Path(__file__).parent.parent
CACHE_FILE = REPO_ROOT / "scripts" / "rf_codes_cache.json"
FANS_FILE  = REPO_ROOT / "scripts" / "fans.json"
DEVICE_IP  = "192.168.1.18"


def load_fans():
    cfg = json.loads(FANS_FILE.read_text())
    return cfg["fans"], cfg["types"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fan",   default=None,         help="Fan device id (default: all fans)")
    p.add_argument("--cmd",   default="light_toggle", help="Command to send (default: light_toggle)")
    p.add_argument("--times", type=int,   default=2,   help="Number of times to send (default: 2)")
    p.add_argument("--delay", type=float, default=5.0, help="Seconds between sends (default: 5)")
    args = p.parse_args()

    fans, types = load_fans()
    codes = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    if not codes:
        sys.exit("Cache empty — run learn_rf_codes.py first")

    if args.fan:
        fans = [f for f in fans if f["id"] == args.fan]
        if not fans:
            sys.exit(f"Fan '{args.fan}' not found in fans.json")

    keys = [f"{fan['id']}/{args.cmd}" for fan in fans]
    missing = [k for k in keys if k not in codes]
    if missing:
        sys.exit(f"Not in cache: {missing}")

    print(f"Connecting to RM4 Pro at {DEVICE_IP}...")
    dev = broadlink.hello(DEVICE_IP)
    dev.auth()
    print("Auth ok.\n")

    for key in keys:
        print(f"Testing: {key}")
        for i in range(args.times):
            print(f"  send {i+1}/{args.times}...")
            dev.send_data(base64.b64decode(codes[key]))
            if i < args.times - 1:
                time.sleep(args.delay)
        print(f"  done\n")


if __name__ == "__main__":
    main()
