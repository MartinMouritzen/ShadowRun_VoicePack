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
    if dst not in by_id and "to_name" in rule:
        # The right speaker can be a character the shipped file never had, because the wrong
        # attribution was the only thing that ever created a bucket for those lines. Create it with
        # the identity a corrected re-extract would produce (name + the actor's own portrait art).
        by_id[dst] = {"id": dst, "name": rule["to_name"], "portrait": rule.get("to_portrait"),
                      "archetype": rule.get("to_archetype"), "bio": None, "lines": []}
        ch["characters"].append(by_id[dst])
        print(f"  created target character {dst} ({rule['to_name']!r})")
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

# ---- renames: same character, wrong identity (see tools/renames.json) -------------------------
# Every per-character file is keyed by the character id, which is derived from the name, so a
# rename has to rekey all of them or the lab silently loses the character's pick, casting, notes
# and takes.
KEYED_FILES = ["picks.json", "casting.json", "char_notes.json", "samples_selection.json",
               "portrait_picks.json", "portraits_ai.json"]
renames = json.load(open(os.path.join(os.path.dirname(__file__), "renames.json"))).get(GAME, [])
for r in renames:
    src, dst = r["from"], r["to"]
    if src not in by_id:
        print(f"  rename {src} -> {dst}: already applied" if dst in by_id else
              f"  rename {src} -> {dst}: SKIPPED, neither id present")
        continue
    if dst in by_id:
        sys.exit(f"ERROR: rename target '{dst}' already exists alongside '{src}'")
    c = by_id[src]
    c["id"] = dst
    c["name"] = r.get("name", c["name"])
    if "portrait" in r: c["portrait"] = r["portrait"]
    if src in takes: takes[dst] = takes.pop(src)
    for k, entry in takes.get(dst, {}).items():
        for tk in entry.get("takes", []):
            if tk["file"].startswith(src + "/"):
                new_rel = dst + tk["file"][len(src):]
                if entry.get("selected") == tk["file"]: entry["selected"] = new_rel
                tk["file"] = new_rel
    old_dir, new_dir = os.path.join(AUDIO, src), os.path.join(AUDIO, dst)
    if os.path.isdir(old_dir) and not os.path.exists(new_dir): shutil.move(old_dir, new_dir)
    touched = []
    for fn in KEYED_FILES:
        p = os.path.join(ROOT, "app", "data", GAME, fn)
        if not os.path.exists(p): continue
        d = json.load(open(p))
        if src not in d: continue
        val = d.pop(src)
        if not (r.get("drop_ai_portrait") and fn in ("portrait_picks.json", "portraits_ai.json")):
            d[dst] = val
            if fn == "samples_selection.json" and isinstance(val, dict) and "name" in val:
                val["name"] = c["name"]
        json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
        touched.append(fn)
    print(f"  renamed {src} -> {dst} ({c['name']!r}), {len(c['lines'])} line(s); rekeyed: "
          f"{', '.join(touched) or 'nothing'}"
          + ("; dropped its AI portrait" if r.get("drop_ai_portrait") else ""))

# ---- sweep per-character data left behind by dropped/renamed characters ----------------------
# A character that no longer exists still has a voice pick, casting shortlist, notes, sample slots
# and AI-portrait records under its old id. They are inert (every consumer keys off characters.json)
# but they rot: the next reader cannot tell a real character from a deleted one.
live = {c["id"] for c in ch["characters"]} | {"narrator", "unattributed", "_barks"}
swept = {}
for fn in KEYED_FILES:
    p = os.path.join(ROOT, "app", "data", GAME, fn)
    if not os.path.exists(p): continue
    d = json.load(open(p))
    dead = [k for k in d if k.startswith("name_") and k not in live]
    if not dead: continue
    for k in dead: d.pop(k)
    json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
    swept[fn] = dead
if swept:
    for fn, dead in swept.items():
        print(f"  swept {len(dead)} orphaned entr(ies) from {fn}: {', '.join(sorted(dead))}")

json.dump(ch, open(CH_PATH, "w"), ensure_ascii=False, indent=1)
json.dump(takes, open(TAKES_PATH, "w"), ensure_ascii=False, indent=1)
print(f"applied {len(rules)} rule(s) and {len(renames)} rename(s) for {GAME}, "
      f"moved {total} line(s) total")
