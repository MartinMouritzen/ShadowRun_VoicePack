#!/usr/bin/env python3
"""Apply tools/unattributed_hand_attribution.json to app/data/dms/characters.json:
move hand-attributed lines from the 'unattributed' bucket to their character (or narrator),
creating new character entries where needed. Lines marked skip/review stay unattributed.
Idempotent: re-running moves nothing twice (moved lines are gone from unattributed)."""
import json, os, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
CH_PATH = os.path.join(ROOT, "app", "data", "dms", "characters.json")
MAP_PATH = os.path.join(os.path.dirname(__file__), "unattributed_hand_attribution.json")

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
    if not target:
        kept.append(rec)
        continue
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
    tag = "SKIP" if rule.get("skip") else "REVIEW" if rule.get("review") else "UNMAPPED"
    print(f"  [{tag}] {rec.get('cn')} n{rec['n']}: {rec['t'][:60]!r}")
