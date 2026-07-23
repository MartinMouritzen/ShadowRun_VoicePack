#!/usr/bin/env python3
"""Apply tools/reattributions.json to app/data/<game>/characters.json: move already-attributed
lines from a wrong character to the right one (see that file's _comment for rationale).

Usage: apply_reattributions.py [dms|dragonfall|hk]   (default dms)

Idempotent: a line (matched by convo id + node index) is moved only if it is currently found
under the rule's 'from' character; if it is already under 'to' (or missing), the rule is a no-op.
Root cause is fixed in extract_game.py; this only corrects the shipped, never-re-extracted file."""
import json, os, sys

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")

ROOT = os.path.join(os.path.dirname(__file__), "..")
CH_PATH = os.path.join(ROOT, "app", "data", GAME, "characters.json")
MAP = json.load(open(os.path.join(os.path.dirname(__file__), "reattributions.json")))
rules = MAP.get(GAME, [])
if not rules:
    print(f"no reattributions for {GAME}"); sys.exit(0)

ch = json.load(open(CH_PATH))
by_id = {c["id"]: c for c in ch["characters"]}

total = 0
for rule in rules:
    convo, nodes = rule["convo"], set(rule["nodes"])
    src, dst = rule["from"], rule["to"]
    if src not in by_id:
        sys.exit(f"ERROR: source char '{src}' not found (convo {convo})")
    if dst not in by_id:
        sys.exit(f"ERROR: target char '{dst}' not found (convo {convo})")
    keep, moved = [], 0
    for ln in by_id[src]["lines"]:
        if ln.get("c") == convo and ln.get("n") in nodes:
            by_id[dst]["lines"].append(ln); moved += 1
        else:
            keep.append(ln)
    by_id[src]["lines"] = keep
    total += moved
    already = sum(1 for ln in by_id[dst]["lines"] if ln.get("c") == convo and ln.get("n") in nodes)
    print(f"  {rule.get('convo_name', convo)}: moved {moved} line(s) {src} -> {dst} "
          f"({already}/{len(nodes)} target nodes now under {dst})")

json.dump(ch, open(CH_PATH, "w"), ensure_ascii=False, indent=1)
print(f"applied {len(rules)} rule(s) for {GAME}, moved {total} line(s) total")
