#!/usr/bin/env python3
"""Apply tools/narration_fixes.json to app/data/<game>/characters.json: mark nodes that are
NARRATION as narration, by wrapping their whole text in {{GM}}...{{/GM}}.

Usage: apply_narration_fixes.py [dms|dragonfall|hk]   (default dms)

Why wrap rather than override the voice: the {{GM}} markers are the pack's own notation for
"the narrator reads this" (build_line_segments.py turns them into 'gm' segments, which live in
the narrator bucket and are cast with the narrator). A per-line voice override would sound the
same today and quietly stop tracking the narrator the moment they are recast.

Idempotent: a node whose text already starts with {{GM}} is left alone. Any take already made
for the node is dropped from takes.json, because it was generated in the character's voice for a
key that now belongs to the narrator; the audio file is left on disk rather than deleted, so the
mistake is recoverable. Run before build_line_segments.py.
"""
import json, os, sys

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")

ROOT = os.path.join(os.path.dirname(__file__), "..")
CH_PATH = os.path.join(ROOT, "app", "data", GAME, "characters.json")
TAKES_PATH = os.path.join(ROOT, "app", "data", GAME, "takes.json")
rules = json.load(open(os.path.join(os.path.dirname(__file__), "narration_fixes.json"))).get(GAME, [])
if not rules:
    print(f"no narration fixes for {GAME}")
    sys.exit(0)

ch = json.load(open(CH_PATH))
by_id = {c["id"]: c for c in ch["characters"]}
takes = json.load(open(TAKES_PATH)) if os.path.exists(TAKES_PATH) else {}

wrapped = already = missing = 0
dropped_takes = []
for rule in rules:
    owner = by_id.get(rule["from"])
    if owner is None:
        print(f"  WARN: no character '{rule['from']}' — skipped")
        missing += len(rule["nodes"])
        continue
    for node in rule["nodes"]:
        line = next((l for l in owner.get("lines") or []
                     if l["c"] == rule["convo"] and l["n"] == node), None)
        if line is None:
            print(f"  WARN: {rule['convo']}_{node} not found under {rule['from']}")
            missing += 1
            continue
        if line["t"].lstrip().startswith("{{GM}}"):
            already += 1
            continue
        line["t"] = "{{GM}}" + line["t"].strip() + "{{/GM}}"
        wrapped += 1
        key = f"{rule['convo']}_{node}"
        entry = (takes.get(rule["from"]) or {}).pop(key, None)
        if entry:
            dropped_takes.append(f"{rule['from']}/{key}")

if wrapped:
    json.dump(ch, open(CH_PATH, "w"), ensure_ascii=False, indent=1)
    if dropped_takes:
        json.dump(takes, open(TAKES_PATH, "w"), ensure_ascii=False, indent=1)
print(f"[{GAME}] narration fixes: {wrapped} node(s) marked as narration, "
      f"{already} already were, {missing} not found")
for k in dropped_takes:
    print(f"    dropped in-character take for {k} (audio kept on disk); regenerate as narrator")
