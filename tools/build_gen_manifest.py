#!/usr/bin/env python3
"""Build the generation job manifest for all appointed (picked) characters + inspect texts.
Resolves each segment's spoken text exactly like the lab (edits > directed > segment/override text),
routes each segment to its bucket's picked voice, and classifies EL (account voice) vs Magnific (mag_).
Skips segments that already have a take. Writes tools/gen/el_jobs.json and tools/gen/mag_jobs.json."""
import json, os, re

ROOT = os.path.join(os.path.dirname(__file__), "..")
D = os.path.join(ROOT, "app", "data")
def L(n): return json.load(open(os.path.join(D, n)))

picks = L("picks.json")
chars = L("characters.json")
SEGS = L("line_segments.json")
takes = L("takes.json")
ov = L("spoken_overrides.json")
directed = L("directed.json")
edits = L("text_edits.json") if os.path.exists(os.path.join(D, "text_edits.json")) else {}
inspect = L("inspect.json") if os.path.exists(os.path.join(D, "inspect.json")) else {}

by_id = {c["id"]: c for c in chars["characters"]}
by_id["narrator"] = {"id": "narrator", "name": "Narrator", "lines": chars["narrator"]["lines"]}

def strip(t): return re.sub(r"\{\{/?[A-Za-z]*\}\}", "", t or "").strip()

def segs_for(cid, base):
    if cid == "narrator" or base not in SEGS:
        return [("char", base)]
    raw = SEGS[base]; nchar = sum(1 for s in raw if s["who"] == "char"); gi = ci = 0; out = []
    for s in raw:
        if s["who"] == "gm": out.append(("gm", f"{base}~g{gi}", s["t"])); gi += 1
        else: out.append(("char", base if nchar == 1 else f"{base}~c{ci}", s["t"])); ci += 1
    return out

def seg_raw(cid, base, l, sk):
    # segment text as the lab derives it: SEGS text for segmented lines, else override/stripped
    if cid != "narrator" and base in SEGS:
        return None  # provided by segs_for tuple
    if base in ov: return ov[base]["spoken"]
    return strip(l["t"])

def eff(segkey, raw):
    if segkey in edits: return edits[segkey]
    if segkey in directed: return directed[segkey]
    return raw

def has_take(bucket, segkey):
    return bool((((takes.get(bucket, {}) or {}).get(segkey, {}) or {}).get("takes")))

def provider(bucket):
    p = picks.get(bucket)
    if not p: return None, None, None
    vid = str(p["voiceId"])
    return ("mag" if vid.startswith("mag_") else "el"), vid, p.get("voiceName")

el_jobs, mag_jobs = [], []
seen = set()

def emit(bucket, segkey, text):
    if not text or segkey in seen: return
    seen.add(segkey)
    if has_take(bucket, segkey): return
    prov, vid, vname = provider(bucket)
    if prov is None: return
    job = {"charId": bucket, "segKey": segkey, "text": text, "voiceId": vid, "voiceName": vname}
    (mag_jobs if prov == "mag" else el_jobs).append(job)

# 1. Iterate EVERY character's lines. Narration (gm) segments route to the narrator (who is cast),
#    so the narrator gets finished game-wide even inside un-cast characters' mixed lines. Character
#    speech (char) segments are only emitted for characters that have a cast voice (emit() no-ops
#    when the bucket has no pick).
for cid in list(by_id.keys()):
    c = by_id.get(cid)
    if not c: continue
    for l in c.get("lines", []):
        base = f'{l["c"]}_{l["n"]}'
        for seg in segs_for(cid, base):
            who, segkey = seg[0], seg[1]
            bucket = "narrator" if who == "gm" else cid
            if who == "gm":
                raw = seg[2]
            else:
                raw = seg[2] if len(seg) > 2 and cid != "narrator" and base in SEGS else seg_raw(cid, base, l, segkey)
            emit(bucket, segkey, eff(segkey, strip(raw)))

# 2. inspect texts -> narrator
for key, v in inspect.items():
    emit("narrator", key, v["spoken"])

os.makedirs(os.path.join(ROOT, "tools", "gen"), exist_ok=True)
json.dump(el_jobs, open(os.path.join(ROOT, "tools/gen/el_jobs.json"), "w"), ensure_ascii=False)
json.dump(mag_jobs, open(os.path.join(ROOT, "tools/gen/mag_jobs.json"), "w"), ensure_ascii=False)
el_c = sum(len(j["text"]) for j in el_jobs)
mag_c = sum(len(j["text"]) for j in mag_jobs)
print(f"EL jobs:  {len(el_jobs):>4}  {el_c:,} chars")
print(f"MAG jobs: {len(mag_jobs):>4}  {mag_c:,} chars  (~{int(mag_c*0.2):,} credits)")
from collections import Counter
print("EL by voice:", dict(Counter(j["voiceName"] for j in el_jobs)))
print("MAG by voice:", dict(Counter(j["voiceName"] for j in mag_jobs)))
