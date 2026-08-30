#!/usr/bin/env python3
"""Apply tools/narration_fixes.json to app/data/<game>/characters.json: mark nodes (or exact
spans inside mixed nodes) as narration by wrapping the text in {{GM}}...{{/GM}}.

Usage: apply_narration_fixes.py [dms|dragonfall|hk]   (default dms)

Why wrap rather than override the voice: the {{GM}} markers are the pack's own notation for
"the narrator reads this" (build_line_segments.py turns them into 'gm' segments, which live in
the narrator bucket and are cast with the narrator). A per-line voice override would sound the
same today and quietly stop tracking the narrator the moment they are recast.

Idempotent: already wrapped nodes/spans are left alone. Character takes whose source text changed
are dropped from takes.json; their audio files are left on disk rather than deleted, so a mistake
is recoverable. Run before build_line_segments.py.
"""
import json, os, re, sys

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

GM_RE = re.compile(r"\{\{GM\}\}[\s\S]*?(?:\{\{/GM\}\}|$)")


def char_parts(text):
    """Current character-owned chunks, keyed the way line_segments will key them."""
    parts = [re.sub(r"\s+", " ", p).strip() for p in GM_RE.split(text) if p.strip()]
    return parts


def drop_changed_character_takes(owner_id, key, before, after):
    """Forget only character segments whose source changed; keep unaffected siblings."""
    old, new = char_parts(before), char_parts(after)
    old_by_key = {key if len(old) == 1 else f"{key}~c{i}": text
                  for i, text in enumerate(old)}
    new_by_key = {key if len(new) == 1 else f"{key}~c{i}": text
                  for i, text in enumerate(new)}
    store = takes.get(owner_id) or {}
    for seg_key, text in old_by_key.items():
        if new_by_key.get(seg_key) == text:
            continue
        if store.pop(seg_key, None):
            dropped_takes.append(f"{owner_id}/{seg_key}")


for rule in rules:
    owner = by_id.get(rule["from"])
    if owner is None:
        print(f"  WARN: no character '{rule['from']}' — skipped")
        missing += len(rule.get("nodes") or []) + len(rule.get("spans") or [])
        continue
    for node in rule.get("nodes") or []:
        line = next((l for l in owner.get("lines") or []
                     if l["c"] == rule["convo"] and l["n"] == node), None)
        if line is None:
            print(f"  WARN: {rule['convo']}_{node} not found under {rule['from']}")
            missing += 1
            continue
        if line["t"].lstrip().startswith("{{GM}}"):
            already += 1
            continue
        before = line["t"]
        line["t"] = "{{GM}}" + before.strip() + "{{/GM}}"
        wrapped += 1
        key = f"{rule['convo']}_{node}"
        drop_changed_character_takes(rule["from"], key, before, line["t"])
    for span in rule.get("spans") or []:
        node, text = span["node"], span["text"]
        line = next((l for l in owner.get("lines") or []
                     if l["c"] == rule["convo"] and l["n"] == node), None)
        if line is None:
            print(f"  WARN: {rule['convo']}_{node} not found under {rule['from']}")
            missing += 1
            continue
        marker = "{{GM}}" + text + "{{/GM}}"
        if marker in line["t"]:
            already += 1
            continue
        if line["t"].count(text) != 1:
            print(f"  WARN: exact narration span not found once in {rule['convo']}_{node}")
            missing += 1
            continue
        before = line["t"]
        line["t"] = before.replace(text, marker, 1)
        wrapped += 1
        key = f"{rule['convo']}_{node}"
        drop_changed_character_takes(rule["from"], key, before, line["t"])

if wrapped:
    json.dump(ch, open(CH_PATH, "w"), ensure_ascii=False, indent=1)
    if dropped_takes:
        json.dump(takes, open(TAKES_PATH, "w"), ensure_ascii=False, indent=1)
print(f"[{GAME}] narration fixes: {wrapped} node(s) marked as narration, "
      f"{already} already were, {missing} not found")
for k in dropped_takes:
    print(f"    dropped stale in-character take for {k} (audio kept on disk)")
