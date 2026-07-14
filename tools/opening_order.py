#!/usr/bin/env python3
"""Print the opening conversations of Dead Man Switch (chapters c01-c03) in play order, so the
opening dialogues can be pre-generated in the lab before an in-game test.

Uses the scene-chapter prefix embedded in each conversation's ui_name (the `cn` field in
characters.json, e.g. "c02-s1_Morgue_Dresden01"). Exact within-scene order is trigger-driven and
not fully static, but voicing all of c01-c03 covers the opening regardless of branch.
"""
import json, os, re, sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(__file__), "..")
chars = json.load(open(os.path.join(ROOT, "app", "data", "characters.json")))

CHAPTERS = sys.argv[1:] or ["c01", "c02", "c03"]

# gather: chapter -> convo_name -> {char, nodes}
by_convo = {}
for ch in chars["characters"] + [dict(chars.get("narrator", {}), id="narrator", name="Narrator")]:
    for l in ch.get("lines", []):
        cn = l.get("cn") or ""
        m = re.match(r"(c\d+)", cn, re.I)
        if not m:
            continue
        chap = m.group(1).lower()
        if chap not in CHAPTERS:
            continue
        rec = by_convo.setdefault(cn, {"chapter": chap, "chars": defaultdict(int)})
        rec["chars"][ch["name"]] += 1

order = sorted(by_convo.items(), key=lambda kv: (kv[1]["chapter"], kv[0]))
total_nodes = 0
cur_chap = None
for cn, rec in order:
    if rec["chapter"] != cur_chap:
        cur_chap = rec["chapter"]
        print(f"\n=== {cur_chap} ===")
    n = sum(rec["chars"].values())
    total_nodes += n
    who = ", ".join(f"{c}({k})" for c, k in sorted(rec["chars"].items(), key=lambda x: -x[1]))
    print(f"  {cn:<44} {n:>3} lines  [{who}]")

print(f"\nTOTAL: {len(order)} conversations, {total_nodes} lines across {CHAPTERS}")
print("To pre-generate the opening: in the lab, generate every segment of these conversations")
print("(each character's lines whose scene prefix is in the list above).")
