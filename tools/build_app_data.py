#!/usr/bin/env python3
"""Build app/data/app_data.js from characters.json + samples_selection.json + casting.json + generated/."""
import json, os, sys, re

ROOT = os.path.join(os.path.dirname(__file__), "..")
def j(p): return json.load(open(os.path.join(ROOT, p)))

chars = j("app/data/characters.json")
sel = j("app/data/samples_selection.json")
casting = j("app/data/casting.json")           # {charId: {main: bool, voices: [{voiceId, voiceName, voiceDesc}]}}
# source of truth = files on disk: app/audio/<charId>/<voiceId>_<key>.mp3
import glob
gen = {}
for p in glob.glob(os.path.join(ROOT, "app/audio/*/*.mp3")):
    if os.path.getsize(p) < 5000: continue
    cid = os.path.basename(os.path.dirname(p))
    base = os.path.basename(p)[:-4]
    vid, _, key = base.partition("_")
    gen.setdefault(cid, {}).setdefault(vid, {})[key] = f"{cid}/{base}.mp3"

by_id = {c["id"]: c for c in chars["characters"]}
by_id["narrator"] = {"id": "narrator", "name": "Narrator (GM)", "portrait": None,
                     "portraitFile": None, "archetype": "The voice of the shadows",
                     "bio": "Reads all {{GM}} narration: scene descriptions, atmosphere, consequences. The most heard voice in the game.",
                     "lines": chars["narrator"]["lines"]}

out = []
for cid, cast in casting.items():
    c = by_id.get(cid)
    s = sel.get(cid)
    if not c or not s: continue
    voices = []
    for v in cast["voices"]:
        vg = gen.get(cid, {}).get(str(v["voiceId"]), {})
        n_samples = 3 if (cast.get("main") and len(cast["voices"]) > 1) else 5
        samples = []
        for l in s["samples"][:n_samples]:
            key = f'{l["c"]}_{l["n"]}'
            samples.append({"t": l["t"], "cn": l.get("cn"), "file": vg.get(key)})
        voices.append({"voiceId": v["voiceId"], "voiceName": v["voiceName"],
                       "voiceDesc": v.get("voiceDesc", ""), "samples": samples})
    out.append({"id": cid, "name": c["name"], "portraitFile": c.get("portraitFile"),
                "archetype": c.get("archetype"), "bio": c.get("bio"),
                "lineCount": len(c["lines"]), "main": bool(cast.get("main")),
                "voices": voices})

order = {cid: i for i, cid in enumerate(casting.keys())}
out.sort(key=lambda c: (not c["main"], -c["lineCount"]))
data = {"characters": out}
with open(os.path.join(ROOT, "app/data/app_data.js"), "w") as f:
    f.write("window.APP_DATA = ")
    json.dump(data, f, ensure_ascii=False)
    f.write(";")
print(f"app_data.js: {len(out)} characters, "
      f"{sum(len(v['samples']) for c in out for v in c['voices'])} sample slots, "
      f"{sum(1 for c in out for v in c['voices'] for s in v['samples'] if s['file'])} with audio")
