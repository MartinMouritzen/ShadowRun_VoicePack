#!/usr/bin/env python3
"""Fold one character id into another when both are the SAME person (see character_merges.json).

The extractor keys a character off the scene prop's name, so a designer who labelled the same NPC
"Raymond" in one scene and "Raymond Tsang" in another produces two characters. Nothing downstream
can tell they are one person, so both get cast -- and the character ends up speaking with two
different voices mid-game. That is the same failure as a misattribution, just arrived at from the
other direction, so it is fixed the same way: in data, before anyone spends credits on it.

This mirrors the lab's own merge action (lab/server.py /api/character/merge) so both routes leave
the data in the same shape: lines and takes move, the TARGET's casting wins, per-character files
are folded, and the merge is recorded in app/data/<game>/merges.json.

Usage: merge_characters.py [dms|dragonfall|hk]   (default dms)
Idempotent: a rule whose source id is already gone is reported and skipped.
"""
import json, os, shutil, sys

GAME = sys.argv[1] if len(sys.argv) > 1 else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")

ROOT = os.path.join(os.path.dirname(__file__), "..")
D = os.path.join(ROOT, "app", "data", GAME)
AUDIO = os.path.join(ROOT, "app", "audio", GAME)
CH_PATH, TAKES_PATH = os.path.join(D, "characters.json"), os.path.join(D, "takes.json")
# same set apply_reattributions.py rekeys on a rename -- every per-character file is keyed by id
KEYED_FILES = ["picks.json", "casting.json", "char_notes.json", "samples_selection.json",
               "portrait_picks.json", "portraits_ai.json"]

rules = json.load(open(os.path.join(os.path.dirname(__file__), "character_merges.json"))).get(GAME, [])
if not rules:
    print(f"no character merges for {GAME}"); sys.exit(0)

ch = json.load(open(CH_PATH))
by_id = {c["id"]: c for c in ch["characters"]}
takes = json.load(open(TAKES_PATH)) if os.path.exists(TAKES_PATH) else {}
merged_ids = []

for r in rules:
    src, dst = r["from"], r["to"]
    if src not in by_id:
        print(f"  {src} -> {dst}: already merged" if dst in by_id else
              f"  {src} -> {dst}: SKIPPED, neither id present")
        continue
    if dst not in by_id:
        sys.exit(f"ERROR: merge target '{dst}' not found (source '{src}' exists)")

    n_lines = len(by_id[src]["lines"])
    by_id[dst]["lines"].extend(by_id[src]["lines"])
    by_id[src]["lines"] = []
    # the target keeps its own portrait/archetype; fill only what it is missing
    for k in ("portrait", "archetype", "bio"):
        if not by_id[dst].get(k) and by_id[src].get(k): by_id[dst][k] = by_id[src][k]

    # takes: rewrite every relative path from the source bucket to the target's, and move the audio
    n_takes = 0
    if src in takes:
        old_dir, new_dir = os.path.join(AUDIO, src), os.path.join(AUDIO, dst)
        for sk, entry in takes.pop(src).items():
            for tk in entry.get("takes", []):
                if tk["file"].startswith(src + "/"):
                    new_rel = dst + tk["file"][len(src):]
                    if entry.get("selected") == tk["file"]: entry["selected"] = new_rel
                    tk["file"] = new_rel
            cur = takes.setdefault(dst, {}).get(sk)
            if cur is None:
                takes[dst][sk] = entry
            else:   # both ids voiced the same segment: keep both takes, target's keeper wins
                have = {t["file"] for t in cur["takes"]}
                cur["takes"].extend(t for t in entry["takes"] if t["file"] not in have)
                cur["selected"] = cur.get("selected") or entry.get("selected")
            n_takes += 1
        if os.path.isdir(old_dir):
            os.makedirs(new_dir, exist_ok=True)
            for sub in os.listdir(old_dir):
                s, t = os.path.join(old_dir, sub), os.path.join(new_dir, sub)
                if os.path.isdir(s):
                    os.makedirs(t, exist_ok=True)
                    for f in os.listdir(s):
                        if not os.path.exists(os.path.join(t, f)):
                            shutil.move(os.path.join(s, f), os.path.join(t, f))
                    if not any(os.scandir(s)): os.rmdir(s)
                elif not os.path.exists(t):
                    shutil.move(s, t)
            if not any(os.scandir(old_dir)): os.rmdir(old_dir)

    # per-character files: the TARGET's casting wins; the source only fills gaps
    folded = []
    for fn in KEYED_FILES:
        p = os.path.join(D, fn)
        if not os.path.exists(p): continue
        d = json.load(open(p))
        if not isinstance(d, dict) or src not in d: continue
        val = d.pop(src)
        if dst not in d and val is not None:
            d[dst] = val
        json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
        folded.append(fn)

    ch["characters"] = [c for c in ch["characters"] if c["id"] != src]
    by_id.pop(src)
    merged_ids.append((src, dst))
    print(f"  merged {src} -> {dst} ({by_id[dst]['name']!r}): {n_lines} line(s)"
          + (f", {n_takes} take group(s)" if n_takes else "")
          + (f"; folded {', '.join(folded)}" if folded else ""))

if merged_ids:
    mp = os.path.join(D, "merges.json")
    merges = json.load(open(mp)) if os.path.exists(mp) else {}
    for src, dst in merged_ids: merges[src] = dst
    json.dump(merges, open(mp, "w"), ensure_ascii=False, indent=1)
    json.dump(ch, open(CH_PATH, "w"), ensure_ascii=False, indent=1)
    if takes or os.path.exists(TAKES_PATH):
        json.dump(takes, open(TAKES_PATH, "w"), ensure_ascii=False, indent=1)
print(f"merged {len(merged_ids)} character(s) for {GAME}")
