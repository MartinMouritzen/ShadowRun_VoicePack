#!/usr/bin/env python3
"""Build the generation job manifest for all appointed (picked) characters + inspect texts.
Resolves each segment's spoken text exactly like the lab (edits > directed > segment/override text),
routes each segment to its bucket's picked voice, and classifies EL (account voice) vs Magnific (mag_).
Skips segments that already have a take. Writes tools/gen/el_jobs.json and tools/gen/mag_jobs.json.

Usage: build_gen_manifest.py [dms|dragonfall|hk] [--recast [charId ...]]   (game defaults to dms)

  --recast [charId ...]   Also emit segments that DO have takes but none in the bucket's currently
                          picked voice. Without this a recast character is silently skipped, because
                          "has a take" is true even when every take is in the voice we just replaced.
                          That is what a character recast needs, and what a misattribution fix needs
                          after lines move to a character cast differently from the one they left.
                          With no ids, applies to every bucket whose takes are all in stale voices."""
import json, os, re, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
# The game is the first positional argument. This tool predates Dragonfall and Hong Kong and read
# app/data/dms unconditionally, so asking it for another pack's jobs silently produced DMS's.
GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "dms"
D = os.path.join(ROOT, "app", "data", GAME)
if not os.path.isdir(D):
    sys.exit(f"no such game data dir: {D}")
def L(n): return json.load(open(os.path.join(D, n)))

picks = L("picks.json")
chars = L("characters.json")
SEGS = L("line_segments.json")
takes = L("takes.json")
ov = L("spoken_overrides.json")
directed = L("directed.json")
edits = L("text_edits.json") if os.path.exists(os.path.join(D, "text_edits.json")) else {}
inspect = L("inspect.json") if os.path.exists(os.path.join(D, "inspect.json")) else {}
# Segment keys that merely repeat another node's line, written by the lab's build_dupes.py. They
# are generated once, at the node they repeat, and inherit that clip in build_voicepack.py.
ALIASES = (L("dupes.json") if os.path.exists(os.path.join(D, "dupes.json")) else {}).get("aliases", {})

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

RECAST = "--recast" in sys.argv
RECAST_IDS = set(sys.argv[sys.argv.index("--recast") + 1:]) if RECAST else set()

def has_take(bucket, segkey):
    ts = (((takes.get(bucket, {}) or {}).get(segkey, {}) or {}).get("takes")) or []
    if not ts: return False
    if RECAST and (not RECAST_IDS or bucket in RECAST_IDS):
        want = (picks.get(bucket) or {}).get("voiceId")
        # every take is in a voice this bucket is no longer cast with -> needs regenerating
        if want and not any(t.get("voiceId") == want for t in ts): return False
    return True

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
    if segkey in (ALIASES.get(bucket) or {}): return
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
print(f"game: {GAME}   (tools/gen/*.json is one shared pair — pass the same game to gen_el.py)")
print(f"EL jobs:  {len(el_jobs):>4}  {el_c:,} chars")
print(f"MAG jobs: {len(mag_jobs):>4}  {mag_c:,} chars  (~{int(mag_c*0.2):,} credits)")
from collections import Counter
print("EL by voice:", dict(Counter(j["voiceName"] for j in el_jobs)))
print("MAG by voice:", dict(Counter(j["voiceName"] for j in mag_jobs)))
