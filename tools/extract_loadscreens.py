#!/usr/bin/env python3
"""Extract loading-screen narration texts (SceneDef.scene_synopsis, protobuf field 22 of
scenes/*.srt.bytes; title = field 20) and MERGE them into app/data/<game>/barks.json as
Narrator entries with kind "loadscreen", keyed bark_<md5(synopsis.strip())[:16]>.

The key must match the plugin's LoadScreenPatch, which hashes SceneLoader.sceneDef
.scene_synopsis.Trim() at runtime — both sides hash the raw trimmed synopsis, NOT the title.
The title is stored alongside for the lab / prompt authoring. NOTE: the loading-screen text
is scene DATA, not part of the background image (loadingImage_* is a separate art asset).

Usage: extract_loadscreens.py <ContentPacks_dir> <game:dms|dragonfall|hk> <pack1[,pack2,...]>
Always additive: existing bark entries (hand attribution, picks) are never touched."""
import glob, hashlib, json, os, sys

SR, GAME, PACKS = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
OUT = os.path.join(os.path.dirname(__file__), "..", "app", "data", GAME, "barks.json")

def rv(b, i):
    r = 0; s = 0
    while True:
        if i >= len(b): raise IndexError
        x = b[i]; i += 1; r |= (x & 0x7f) << s
        if not x & 0x80: return r, i
        s += 7
def fields(b):
    i = 0; n = len(b)
    while i < n:
        try:
            tag, i = rv(b, i)
            f, wt = tag >> 3, tag & 7
            if wt == 0:
                v, i = rv(b, i); yield f, wt, v
            elif wt == 1: yield f, wt, b[i:i+8]; i += 8
            elif wt == 2:
                l, i = rv(b, i)
                if i + l > n: return
                yield f, wt, b[i:i+l]; i += l
            elif wt == 5: yield f, wt, b[i:i+4]; i += 4
            else: return
        except IndexError: return

found = {}
for p in PACKS:
    for sf in sorted(glob.glob(os.path.join(SR, p, "data/scenes/*.srt.bytes"))):
        data = open(sf, 'rb').read()
        title = syn = None
        for f, wt, v in fields(data):
            if wt != 2: continue
            try:
                if f == 20: title = v.decode('utf-8')
                elif f == 22: syn = v.decode('utf-8')
            except Exception: pass
        if not syn or not syn.strip(): continue
        syn = syn.strip()
        key = "bark_" + hashlib.md5(syn.encode('utf-8')).hexdigest()[:16]
        scene = os.path.basename(sf).split('.')[0]
        if key in found: found[key]["scenes"].append(scene)
        else: found[key] = {"text": syn, "speaker": "Narrator", "sheetId": None, "archetype": None,
                            "gender": "?", "portrait": None, "nonverbal": False, "count": 1,
                            "kind": "loadscreen", "title": (title or "").strip(), "scenes": [scene]}

barks = json.load(open(OUT)) if os.path.exists(OUT) else {}
new = [k for k in found if k not in barks]
for k in new: barks[k] = found[k]
json.dump(barks, open(OUT, "w"), ensure_ascii=False, indent=1)
print(f"[{GAME}] loadscreens: {len(found)} unique ({sum(len(v['text']) for v in found.values())} chars), "
      f"+{len(new)} new bark entries (existing untouched)")
