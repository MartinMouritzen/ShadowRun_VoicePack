#!/usr/bin/env python3
"""Build app/data/<game>/spoken_overrides.json: per-line SPOKEN text for lines containing $()
variables (incl. the $+() and $(L.*) variants). Screen text stays untouched; audio uses the
override. Rules live in spoken_rules.py (shared with build_line_segments.py); lines they can't
fully clean are listed for hand-rewriting in the per-game HAND file (always wins over rules).

Usage: build_spoken_overrides.py [dms|dragonfall|hk]   (default dms)
Hand files: tools/spoken_hand_rewrites.json (dms, legacy name) /
            tools/spoken_hand_rewrites_<game>.json (dragonfall, hk)
Unresolved: tools/spoken_unresolved.json (dms) / tools/spoken_unresolved_<game>.json"""
import json, re, sys, os
from spoken_rules import mechanical, has_var

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    print(f"ERROR: unknown game '{GAME}'", file=sys.stderr); sys.exit(1)

ROOT = os.path.join(os.path.dirname(__file__), "..")
HERE = os.path.dirname(__file__)
SUF = "" if GAME == "dms" else f"_{GAME}"
c = json.load(open(os.path.join(ROOT, f"app/data/{GAME}/characters.json")))

HAND = {}
handfile = os.path.join(HERE, f"spoken_hand_rewrites{SUF}.json")
if os.path.exists(handfile):
    HAND = json.load(open(handfile))

def strip_gm(t):
    return re.sub(r'\{\{GM\}\}.*?(\{\{/GM\}\}|$)', ' ', t, flags=re.S)

overrides = {}
unresolved = []
def process(cid, cname, lines, is_narrator=False):
    for l in lines:
        hv = has_var(l['t'])
        if not hv and (is_narrator or '{{' not in l['t']):
            continue
        key = f"{l['c']}_{l['n']}"
        if key in HAND:
            overrides[key] = {"char": cname, "original": l['t'], "spoken": HAND[key], "source": "hand"}
            continue
        if not hv:
            continue  # GM-span-only lines are handled at generation time, no override needed
        s = l['t'] if is_narrator else strip_gm(l['t'])
        s = mechanical(re.sub(r'\{\{/?[A-Za-z]*\}\}', '', s)).strip()
        if '$(' in s or not s:
            # {{GM}}-containing char lines are segmented: their fixes live in the per-game
            # hand-SEGMENTS file and are reported by build_line_segments.py — don't double-report.
            if is_narrator or '{{GM}}' not in l['t']:
                unresolved.append({"key": key, "char": cname, "text": l['t']})
        else:
            overrides[key] = {"char": cname, "original": l['t'], "spoken": s, "source": "rules"}

for ch in c["characters"]:
    process(ch["id"], ch["name"], ch["lines"])
if "narrator" in c:
    process("narrator", "Narrator", c["narrator"]["lines"], is_narrator=True)

json.dump(overrides, open(os.path.join(ROOT, f"app/data/{GAME}/spoken_overrides.json"), "w"),
          ensure_ascii=False, indent=1)
print(f"[{GAME}] overrides: {len(overrides)} ({sum(1 for v in overrides.values() if v['source']=='hand')} hand)")
print(f"[{GAME}] unresolved (need hand rewrite): {len(unresolved)}")
json.dump(unresolved, open(os.path.join(HERE, f"spoken_unresolved{SUF}.json"), "w"),
          ensure_ascii=False, indent=1)
