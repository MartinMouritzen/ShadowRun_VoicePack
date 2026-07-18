#!/usr/bin/env python3
"""Build app/data/<game>/char_notes.json for dragonfall / hk.

Reads authored notes from tools/char_notes_src/<game>.json
  {cid: {"bio", "direction", "kw": [..], "gender": "male"|"female"|null, "age": ...}}
plus the shared Magnific catalog, and emits the same shape DMS uses:
  {cid: {"bio", "direction", "gender", "suggestions": [{voice_id, name, why} x8]}}
covering every character in characters.json plus the narrator. Characters missing
from the authored file get a generic entry derived from portrait/name.

Usage: build_char_notes_game.py <game>
"""
import json, os, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("dragonfall", "hk"):
        sys.exit(__doc__)
    game = sys.argv[1]
    cat = json.load(open(os.path.join(ROOT, "app/data/magnific_voices.json")))["voices"]
    cat = [v for v in cat if (v.get("lang") or "English") == "English"]
    chars = json.load(open(os.path.join(ROOT, f"app/data/{game}/characters.json")))
    src = json.load(open(os.path.join(ROOT, f"tools/char_notes_src/{game}.json")))

    def generic_for(name, portrait):
        n, p = name.lower(), (portrait or "").lower()
        if any(w in n for w in ["terminal", "computer", "console", "drone", "system", "camera", "turret"]):
            return ("A machine interface.", "Flat synthetic delivery; clipped and inhuman.",
                    ["robotic", "flat", "synthetic", "clear"], None, None)
        if any(w in n for w in ["spirit", "ghost", "shade", "elemental"]):
            return ("A being from the astral plane.", "Ethereal and unsettling; speaks from somewhere else.",
                    ["ethereal", "whispery", "deep", "otherworldly"], None, None)
        fem = "female" in p
        if fem:
            return ("A local of the setting.", "Grounded, everyday delivery with a hint of street wariness.",
                    ["natural", "casual", "warm", "clear"], "female", None)
        return ("A local of the setting.", "Grounded, everyday delivery with a hint of street wariness.",
                ["natural", "casual", "gruff", "clear"], "male" if "male" in p else None, None)

    def score(v, kws, gender, age):
        if gender and v.get("gender") and v["gender"] != gender: return -1
        hay = f'{v.get("name","")} {v.get("desc","")} {v.get("accent","")} {v.get("use","")} {v.get("age","")}'.lower()
        s = sum(2 for k in kws if k in hay)
        if v.get("gender") == gender: s += 1
        if age and v.get("age") == age: s += 1
        if v.get("source") == "mine": s += 0.5   # already in account: no slot juggling
        return s

    used_count = {}
    def suggest(kws, gender, age, n=8):
        scored = [(score(v, kws, gender, age), v) for v in cat]
        scored = [(s, v) for s, v in scored if s >= 0]
        scored.sort(key=lambda sv: -(sv[0] - 0.6 * used_count.get(sv[1]["voice_id"], 0)))
        out = []
        for s, v in scored:
            out.append({"voice_id": v["voice_id"], "name": v["name"],
                        "why": (v.get("desc") or "")[:90]})
            used_count[v["voice_id"]] = used_count.get(v["voice_id"], 0) + 1
            if len(out) == n: break
        return out

    notes, from_src, from_generic = {}, 0, []
    todo = [{"id": "narrator", "name": "Narrator (GM)", "portrait": None}] + chars["characters"]
    for c in todo:
        cid = c["id"]
        e = src.get(cid)
        if e:
            bio, direction, kws, gender, age = e["bio"], e["direction"], e.get("kw", []), e.get("gender"), e.get("age")
            from_src += 1
        else:
            bio, direction, kws, gender, age = generic_for(c["name"], c.get("portrait"))
            from_generic.append(cid)
        notes[cid] = {"bio": bio, "direction": direction, "gender": gender,
                      "suggestions": suggest(kws, gender, age)}

    out_path = os.path.join(ROOT, f"app/data/{game}/char_notes.json")
    json.dump(notes, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"{game}: {len(notes)} notes ({from_src} authored, {len(from_generic)} generic fallback)")
    if from_generic:
        print("generic fallback for:", ", ".join(from_generic))
    empty = [c for c, v in notes.items() if not v["suggestions"]]
    print("no suggestions for:", empty or "none")
    unused = [cid for cid in src if cid != "narrator" and cid not in {c["id"] for c in todo}]
    if unused:
        print("WARNING authored ids not in characters.json:", ", ".join(unused))

if __name__ == "__main__":
    main()
