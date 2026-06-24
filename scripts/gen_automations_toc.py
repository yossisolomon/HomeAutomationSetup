#!/usr/bin/env python3
"""Generate / validate the automations ToC in docs/automations.md.

Usage:
  gen_automations_toc.py            # regenerate the AUTOGEN block in docs/automations.md
  gen_automations_toc.py --check    # validate meta presence + unique names; exit 1 on problems
"""
import re
import sys
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
AUTOMATIONS = REPO / "config" / "automations.yaml"
SCRIPTS = REPO / "config" / "scripts.yaml"
FLOWS_DIR = REPO / "nodered" / "data" / "flows"
TOC = REPO / "docs" / "automations.md"

START = "<!-- AUTOGEN:automations START -->"
END = "<!-- AUTOGEN:automations END -->"

META_RE = re.compile(r"#\s*meta:\s*(.+?)\s*$")
INFO_META_RE = re.compile(r"meta:\s*(.+?)\s*$")
ALIAS_RE = re.compile(r'^\s*-?\s*alias:\s*(.+?)\s*$')
SCRIPT_KEY_RE = re.compile(r'^([A-Za-z0-9_][A-Za-z0-9_-]*):\s*$')


def parse_meta(s):
    out = {}
    for part in s.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class Entry:
    def __init__(self, name, engine, file, meta):
        self.name = name
        self.engine = engine
        self.file = file
        self.meta = meta


def parse_automations(path):
    entries = []
    if not path.exists():
        return entries
    last_meta = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            mm = META_RE.search(line)
            if mm:
                last_meta = parse_meta(mm.group(1))
            continue
        am = ALIAS_RE.match(line)
        if am:
            name = am.group(1).strip().strip('"').strip("'")
            entries.append(Entry(name, "HA-automation", path.name, last_meta))
            last_meta = None
    return entries


def parse_scripts(path):
    entries = []
    if not path.exists():
        return entries
    pending_meta = None   # a "# meta:" comment, applied to the next script key
    current = None
    current_meta = None
    alias = None

    def flush():
        nonlocal current, alias, current_meta
        if current is not None:
            entries.append(Entry(alias or current, "HA-script", path.name, current_meta))
        current, alias, current_meta = None, None, None

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            mm = META_RE.search(line)
            if mm:
                pending_meta = parse_meta(mm.group(1))
            continue
        km = SCRIPT_KEY_RE.match(line)
        if km:
            flush()
            current = km.group(1)
            current_meta = pending_meta   # consume the meta seen just above this key
            pending_meta = None
            continue
        am = ALIAS_RE.match(line)
        if am and current is not None:
            alias = am.group(1).strip().strip('"').strip("'")
    flush()
    return entries


def parse_flows(dirpath):
    entries = []
    if not dirpath.exists():
        return entries
    for f in sorted(dirpath.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        nodes = data if isinstance(data, list) else data.get("flows", [])
        for n in nodes:
            if isinstance(n, dict) and n.get("type") == "tab":
                meta = None
                for ln in (n.get("info", "") or "").splitlines():
                    im = INFO_META_RE.search(ln)
                    if im:
                        meta = parse_meta(im.group(1))
                        break
                entries.append(Entry(n.get("label", "(unnamed)"), "NodeRED", f.name, meta))
    return entries


def collect():
    return parse_automations(AUTOMATIONS) + parse_scripts(SCRIPTS) + parse_flows(FLOWS_DIR)


def render_table(entries):
    header = ("| name | engine | file | intent | waf | mode |\n"
              "|------|--------|------|--------|-----|------|")
    if not entries:
        return header + "\n| _(none yet)_ | | | | | |"
    rows = []
    for e in sorted(entries, key=lambda x: (x.engine, x.name)):
        m = e.meta or {}
        rows.append("| {} | {} | {} | {} | {} | {} |".format(
            e.name, e.engine, e.file,
            m.get("intent", "—"), m.get("waf", "—"), m.get("mode", "—")))
    return header + "\n" + "\n".join(rows)


def replace_block(doc, table):
    text = doc.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    new = START + "\n" + table + "\n" + END
    if not pattern.search(text):
        raise SystemExit("AUTOGEN markers not found in {}".format(doc))
    doc.write_text(pattern.sub(new, text), encoding="utf-8")


def check(entries):
    problems = []
    seen = {}
    for e in entries:
        if e.meta is None or not e.meta.get("mode"):
            problems.append("missing meta annotation: {} ({})".format(e.name, e.file))
        seen.setdefault(e.name, []).append(e.file)
    for name, files in seen.items():
        if len(files) > 1:
            problems.append("duplicate name '{}' in {}".format(name, ", ".join(files)))
    return problems


def main(argv):
    entries = collect()
    if "--check" in argv:
        problems = check(entries)
        if problems:
            print("ToC validation failed:", file=sys.stderr)
            for p in problems:
                print("  - " + p, file=sys.stderr)
            return 1
        return 0
    replace_block(TOC, render_table(entries))
    print("Regenerated {} ({} automations).".format(TOC, len(entries)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
