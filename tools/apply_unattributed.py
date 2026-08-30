#!/usr/bin/env python3
"""Apply tools/unattributed_hand_attribution[_<game>].json to app/data/<game>/characters.json:
move hand-attributed lines from the 'unattributed' bucket to their character (or narrator),
creating new character entries where needed. Lines marked skip/review stay unattributed.
Idempotent: re-running moves nothing twice (moved lines are gone from unattributed).

Usage: apply_unattributed.py [dms|dragonfall|hk]   (default dms)
The tool was hardcoded to DMS, which is why Dragonfall's 165 and Hong Kong's 540 unattributed
lines had never been through it - and an unattributed line is invisible in the lab and silent in
the pack, so they were not merely mis-filed, they were unvoiceable."""
import json, os, sys

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")
ROOT = os.path.join(os.path.dirname(__file__), "..")
CH_PATH = os.path.join(ROOT, "app", "data", GAME, "characters.json")
_suffix = "" if GAME == "dms" else f"_{GAME}"
MAP_PATH = os.path.join(os.path.dirname(__file__), f"unattributed_hand_attribution{_suffix}.json")

amap = json.load(open(MAP_PATH))
ch = json.load(open(CH_PATH))
by_id = {c["id"]: c for c in ch["characters"]}

# create new character entries (same schema as extracted chars)
for nc in amap.get("new_characters", []):
    if nc["id"] not in by_id:
        entry = {"id": nc["id"], "name": nc["name"], "portrait": None, "archetype": None,
                 "bio": nc.get("note"), "lines": [], "portraitFile": None}
        ch["characters"].append(entry)
        by_id[nc["id"]] = entry

moved = {"narrator": 0}
kept = []
for rec in ch["unattributed"]["lines"]:
    rule = amap["convos"].get(rec["c"])
    if not rule or rule.get("skip") or rule.get("review"):
        kept.append(rec)
        continue
    target = (rule.get("nodes") or {}).get(str(rec["n"])) or rule.get("to")
    # A single node can opt out of its conversation's default: two lines of the safeboat call are a
    # farewell from runners the game never names, and guessing at them would be worse than silence.
    if target in ("skip", "review"):
        kept.append(rec)
        continue
    if not target:
        kept.append(rec)
        continue
    rec["attribution"] = "manual-unattributed-review"
    rec["attributionReason"] = rule.get("why") or (
        f"Hand-reviewed node assignment from {rec.get('cn') or rec['c']}.")
    if target == "narrator":
        ch["narrator"]["lines"].append(rec)
        moved["narrator"] += 1
    else:
        if target not in by_id:
            sys.exit(f"ERROR: target char '{target}' not found (convo {rec['c']} node {rec['n']})")
        by_id[target]["lines"].append(rec)
        moved[target] = moved.get(target, 0) + 1

ch["unattributed"]["lines"] = kept
st = ch.get("stats", {})
total_moved = sum(moved.values())
st["attributed"] = st.get("attributed", 0) + total_moved - moved["narrator"]
st["narrator"] = st.get("narrator", 0) + moved["narrator"]
st["unattributed"] = len(kept)
json.dump(ch, open(CH_PATH, "w"), ensure_ascii=False, indent=1)

print(f"moved {total_moved} lines, {len(kept)} left unattributed (skip/review):")
for k, v in sorted(moved.items(), key=lambda x: -x[1]):
    print(f"  {v:3d} -> {k}")
for rec in kept:
    rule = amap["convos"].get(rec["c"], {})
    node_target = (rule.get("nodes") or {}).get(str(rec["n"]))
    tag = "SKIP" if rule.get("skip") or node_target == "skip" else \
          "REVIEW" if rule.get("review") or node_target == "review" else "UNMAPPED"
    print(f"  [{tag}] {rec.get('cn')} n{rec['n']}: {rec['t'][:60]!r}")
