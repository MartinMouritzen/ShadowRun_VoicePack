#!/usr/bin/env python3
"""Apply tools/reattributions.json to app/data/<game>/characters.json: move already-attributed
lines from a wrong character to the right one (see that file's _comment for rationale).

Usage: apply_reattributions.py [dms|dragonfall|hk]   (default dms)

Idempotent: a line (matched by convo id + node index) is moved only if it is currently found
under the rule's 'from' character; if it is already under 'to' (or missing), the rule is a no-op.
Root cause is fixed in extract_game.py; this only corrects the shipped, never-re-extracted file.

Any takes already generated for a moved line follow it: takes.json is bucketed by character id
and build_voicepack.py looks a line up under its OWNING character, so a line that moves without
its takes silently loses its audio. The take audio moves on disk too (app/audio/<game>/<charId>/),
and the 'file' path in takes.json is rewritten to match. GM segments (~gN) live under 'narrator'
and never move; character segments (~cN) do."""
import json, os, shutil, sys

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")

ROOT = os.path.join(os.path.dirname(__file__), "..")
CH_PATH = os.path.join(ROOT, "app", "data", GAME, "characters.json")
TAKES_PATH = os.path.join(ROOT, "app", "data", GAME, "takes.json")
AUDIO = os.path.join(ROOT, "app", "audio", GAME)
MAP = json.load(open(os.path.join(os.path.dirname(__file__), "reattributions.json")))
rules = MAP.get(GAME, [])
if not rules:
    print(f"no reattributions for {GAME}"); sys.exit(0)

ch = json.load(open(CH_PATH))
by_id = {c["id"]: c for c in ch["characters"]}
takes = json.load(open(TAKES_PATH)) if os.path.exists(TAKES_PATH) else {}

def move_takes(src, dst, convo, nodes):
    """Carry every take for these nodes from bucket src to bucket dst; returns keys moved."""
    if src not in takes: return []
    bases = {f"{convo}_{n}" for n in nodes}
    keys = [k for k in takes[src]
            if k in bases or (k.split("~")[0] in bases and k.split("~")[1].startswith("c"))]
    for k in keys:
        entry = takes[src].pop(k)
        for tk in entry.get("takes", []):
            old_rel = tk["file"]
            if not old_rel.startswith(src + "/"): continue
            new_rel = dst + old_rel[len(src):]
            old_abs = os.path.join(AUDIO, *old_rel.split("/"))
            new_abs = os.path.join(AUDIO, *new_rel.split("/"))
            if os.path.exists(new_abs) or os.path.exists(old_abs):
                if not os.path.exists(new_abs):
                    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                    shutil.move(old_abs, new_abs)
                if entry.get("selected") == old_rel: entry["selected"] = new_rel
                tk["file"] = new_rel
            else:
                print(f"    WARN: take audio missing, left path as-is: {old_rel}")
        cur = takes.setdefault(dst, {}).get(k)
        if cur is None:
            takes[dst][k] = entry
        else:   # target already had takes for this line: keep both, target's keeper wins
            have = {t["file"] for t in cur["takes"]}
            cur["takes"].extend(t for t in entry["takes"] if t["file"] not in have)
            cur["selected"] = cur.get("selected") or entry.get("selected")
    if not takes[src]: takes.pop(src)
    return keys

total = 0
dropped = []
for rule in rules:
    convo, nodes = rule["convo"], set(rule["nodes"])
    src, dst = rule["from"], rule["to"]
    if dst not in by_id:
        sys.exit(f"ERROR: target char '{dst}' not found (convo {convo})")
    if src not in by_id:
        # A previous run emptied the source and dropped it. That is only OK if the lines really
        # did land on the target; anything else means the file is not what this rule expects.
        here = sum(1 for ln in by_id[dst]["lines"] if ln.get("c") == convo and ln.get("n") in nodes)
        if here == len(nodes):
            print(f"  {rule.get('convo_name', convo)}: already applied ({src} gone, "
                  f"{here}/{len(nodes)} nodes under {dst})")
            continue
        sys.exit(f"ERROR: source char '{src}' not found and only {here}/{len(nodes)} of its nodes "
                 f"are under '{dst}' (convo {convo})")
    keep, moved = [], 0
    for ln in by_id[src]["lines"]:
        if ln.get("c") == convo and ln.get("n") in nodes:
            by_id[dst]["lines"].append(ln); moved += 1
        else:
            keep.append(ln)
    by_id[src]["lines"] = keep
    total += moved
    tk_moved = move_takes(src, dst, convo, nodes) if moved else []
    already = sum(1 for ln in by_id[dst]["lines"] if ln.get("c") == convo and ln.get("n") in nodes)
    print(f"  {rule.get('convo_name', convo)}: moved {moved} line(s) {src} -> {dst} "
          f"({already}/{len(nodes)} target nodes now under {dst})"
          + (f", carried {len(tk_moved)} take group(s)" if tk_moved else ""))
    if rule.get("drop_source_when_empty") and not by_id[src]["lines"]:
        dropped.append(src)

if dropped:
    ch["characters"] = [c for c in ch["characters"] if c["id"] not in dropped]
    print(f"dropped {len(dropped)} now-empty source character(s): {', '.join(dropped)}")
    for src in dropped:
        if src in takes:
            sys.exit(f"ERROR: '{src}' has no lines left but still owns takes for "
                     f"{sorted(takes[src])} — a rule is missing")
        d = os.path.join(AUDIO, src)
        for sub in (os.path.join(d, "takes"), d):   # takes/ first, then the character dir
            if os.path.isdir(sub) and not any(os.scandir(sub)): os.rmdir(sub)
json.dump(ch, open(CH_PATH, "w"), ensure_ascii=False, indent=1)
json.dump(takes, open(TAKES_PATH, "w"), ensure_ascii=False, indent=1)
print(f"applied {len(rules)} rule(s) for {GAME}, moved {total} line(s) total")
