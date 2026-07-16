#!/usr/bin/env python3
"""Merge generation results (EL jsonl + Magnific slice json) into takes.json.
Single writer of takes.json — run after all generation workers finish. Appends each take and
auto-selects it if the segment has no keeper yet. Idempotent per (segKey, file)."""
import json, os, glob

ROOT = os.path.join(os.path.dirname(__file__), "..")
TAKES = os.path.join(ROOT, "app", "data", "dms", "takes.json")
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
    chars = json.load(open(os.path.join(ROOT, "app", "data", "dms", "characters.json")))
    SEGS = json.load(open(os.path.join(ROOT, "app", "data", "dms", "line_segments.json")))
    inspp = os.path.join(ROOT, "app", "data", "dms", "inspect.json")
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
        ap = os.path.join(ROOT, "app", "audio", *rel.split("/"))
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
