#!/usr/bin/env python3
"""Merge generation results (EL jsonl + Magnific slice json) into takes.json.
Single writer of takes.json — run after all generation workers finish. Appends each take and
auto-selects it if the segment has no keeper yet. Idempotent per (segKey, file).

Usage: merge_takes.py [dms|dragonfall|hk]   (default dms)

This was hardcoded to DMS in three places -- the take store, the data used to validate segKeys,
and the audio existence check. gen_el.py deliberately does not write takes.json itself (it would
race the Magnific workers), so it leaves its results in gen/el_results.jsonl for this script to
land. With the DMS paths, a Dragonfall run validated its segKeys against DMS's lines, rejected
every one, and reported a clean "merged 0" -- so ElevenLabs narrator segments were generated,
paid for, written to disk, and then never entered the take store. They were invisible in the lab
and silent in the pack, and the run looked successful. el_results.jsonl is cumulative across
games, but the segKey and audio-path checks below are per-game, so entries for other packs are
filtered out naturally."""
import json, os, glob, sys

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}' (expected dms|dragonfall|hk)")

ROOT = os.path.join(os.path.dirname(__file__), "..")
TAKES = os.path.join(ROOT, "app", "data", GAME, "takes.json")
GEN = os.path.join(ROOT, "tools", "gen")

def load_results():
    out = []
    p = os.path.join(GEN, "el_results.jsonl")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line: out.append(json.loads(line))
    for f in glob.glob(os.path.join(GEN, "mag_results", "*.json")):
        for r in json.load(open(f)):
            out.append(r)
    return out

def valid_segkeys():
    """Every real line's base + ~gN/~cN + inspect keys — rejects hallucinated junk from workers."""
    import re
    chars = json.load(open(os.path.join(ROOT, "app", "data", GAME, "characters.json")))
    SEGS = json.load(open(os.path.join(ROOT, "app", "data", GAME, "line_segments.json")))
    inspp = os.path.join(ROOT, "app", "data", GAME, "inspect.json")
    valid = set(json.load(open(inspp)).keys()) if os.path.exists(inspp) else set()
    rows = list(chars["characters"]) + [dict(chars["narrator"], id="narrator")]
    for c in rows:
        for l in c.get("lines", []):
            base = f'{l["c"]}_{l["n"]}'; valid.add(base)
            segs = SEGS.get(base)
            if segs:
                nchar = sum(1 for s in segs if s["who"] == "char"); gi = ci = 0
                for s in segs:
                    if s["who"] == "gm": valid.add(f"{base}~g{gi}"); gi += 1
                    else: valid.add(base if nchar == 1 else f"{base}~c{ci}"); ci += 1
    return valid

def main():
    takes = json.load(open(TAKES)) if os.path.exists(TAKES) else {}
    results = load_results()
    valid = valid_segkeys()
    added = 0; rejected = 0
    for r in results:
        if not isinstance(r, dict) or not r.get("segKey") or not r.get("charId"):
            rejected += 1; continue   # malformed worker output (e.g. a bare string)
        if r.get("status") == "error" or not r.get("file"):
            continue
        cid, sk, rel = r["charId"], r["segKey"], r["file"]
        if sk not in valid:
            rejected += 1; continue   # hallucinated / stale segKey — never enter takes.json
        # verify the audio actually exists and is non-trivial
        # audio moved under a per-game subdir when the lab went multi-game. Without the game in
        # this path the existence check never passes and every result is skipped in silence -- the
        # script reports "merged 0" and looks like a no-op rather than a broken path.
        ap = os.path.join(ROOT, "app", "audio", GAME, *rel.split("/"))
        if not (os.path.exists(ap) and os.path.getsize(ap) > 5000):
            continue
        arr = takes.setdefault(cid, {}).setdefault(sk, {"selected": None, "takes": []})
        if any(t["file"] == rel for t in arr["takes"]):
            continue
        arr["takes"].append({"file": rel, "voiceId": r.get("voiceId"), "voiceName": r.get("voiceName"),
                             "stability": r.get("stability", 0), "chars": r.get("chars", 0),
                             "ts": r.get("ts", 0)})
        if arr["selected"] is None:
            arr["selected"] = rel
        added += 1
    tmp = TAKES + ".tmp"
    json.dump(takes, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, TAKES)
    print(f"merged {added} new takes from {len(results)} results"
          + (f" ({rejected} junk segKeys rejected)" if rejected else ""))

if __name__ == "__main__":
    main()
