#!/usr/bin/env python3
"""Copy character portrait PNGs from a game's ContentPacks into app/portraits/<game>/
and set portraitFile on the entries in app/data/<game>/characters.json.

Portrait resolution: character "portrait" name (e.g. NPC_HumanFemale_Glory) maps to
<lowercase>.png searched across every ContentPacks/*/art/portraits/ dir. When the same
filename exists in several packs, the pack listed earliest in the priority list wins.

Usage: extract_portraits_game.py <ContentPacks-dir> <game> <pack1,pack2,...>
  e.g. extract_portraits_game.py ".../Dragonfall_Data/StreamingAssets/ContentPacks" dragonfall DragonfallExtended,berlin,seattle
"""
import json, os, shutil, sys, glob, re

ROOT = os.path.join(os.path.dirname(__file__), "..")

# ---- scene-actor portrait fallback -------------------------------------------------------------
# A name-cast speaker (e.g. Gino) often has NO portrait on its dialogue record, yet the same
# character placed as a scene actor carries ci_portrait (Gino -> NPC_HumanMale_Gino). Dialogue
# extraction never merges that in, so those characters looked portrait-less and got a needless AI
# portrait. Recover the real portrait by matching the character name to a scene actor's ci_name.
# Minimal protobuf reader (same wire walk as extract_extras_game.py); scenes/maps only.
def _rv(b, i):
    r = 0; s = 0
    while True:
        if i >= len(b): raise IndexError
        x = b[i]; i += 1; r |= (x & 0x7f) << s
        if not x & 0x80: return r, i
        s += 7
def _fields(b):
    i = 0; n = len(b)
    while i < n:
        try:
            tag, i = _rv(b, i); f, wt = tag >> 3, tag & 7
            if wt == 0: v, i = _rv(b, i); yield f, wt, v
            elif wt == 1: yield f, wt, b[i:i+8]; i += 8
            elif wt == 2:
                l, i = _rv(b, i)
                if i + l > n: return
                yield f, wt, b[i:i+l]; i += l
            elif wt == 5: yield f, wt, b[i:i+4]; i += 4
            else: return
        except IndexError: return
def _s(b):
    try: return b.decode("utf-8")
    except Exception: return None
def _sub1(v):
    for f, wt, x in _fields(v):
        if f == 1 and wt == 2: return _s(x)
    return None
def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def scene_actor_portraits(packs_dir, packs):
    """norm(ci_name) -> ci_portrait, scanned from the listed packs' scenes+maps (PropInstance
    field 4 -> CharacterInfo field 100: name=field 8, portrait=field 40). First value per name
    wins; callers should still verify the portrait resolves to a real file."""
    out = {}
    for pk in packs:
        for sf in (glob.glob(os.path.join(packs_dir, pk, "data/scenes/*.srt.bytes")) +
                   glob.glob(os.path.join(packs_dir, pk, "data/maps/*.srm.bytes"))):
            data = open(sf, "rb").read()
            for prop in (v for f, wt, v in _fields(data) if f == 4 and wt == 2):
                ci = None
                for f, wt, v in _fields(prop):
                    if f == 100 and wt == 2: ci = v; break
                if ci is None: continue
                nm = port = None
                for f, wt, v in _fields(ci):
                    if f == 8 and wt == 2: nm = _s(v)
                    elif f == 40 and wt == 2: port = _sub1(v) or _s(v)
                if nm and port:
                    out.setdefault(_norm(nm), port)
    return out

def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    packs_dir, game, priority = sys.argv[1], sys.argv[2], sys.argv[3].split(",")

    chars_path = os.path.join(ROOT, "app", "data", game, "characters.json")
    data = json.load(open(chars_path))

    # lowercase filename -> source path, earliest-priority pack wins
    def pack_rank(pack):
        return priority.index(pack) if pack in priority else len(priority)
    catalog = {}
    for pack in sorted(os.listdir(packs_dir), key=pack_rank):
        pdir = os.path.join(packs_dir, pack, "art", "portraits")
        if not os.path.isdir(pdir):
            continue
        for f in os.listdir(pdir):
            if f.lower().endswith(".png"):
                catalog.setdefault(f.lower(), os.path.join(pdir, f))

    out_dir = os.path.join(ROOT, "app", "portraits", game)
    os.makedirs(out_dir, exist_ok=True)

    # name -> real portrait, recovered from scene actors for characters whose dialogue record
    # carries no portrait name (e.g. Gino).
    scene_ports = scene_actor_portraits(packs_dir, priority)

    matched = missing = blank = recovered = 0
    missing_names = []
    for c in data["characters"]:
        p = c.get("portrait")
        if not p:
            # dialogue record had no portrait: fall back to the scene-actor roster by name, but
            # only when it resolves to a portrait file that actually exists (skips blank/junk
            # ci_portrait values so those characters still get their AI portrait as before).
            cand = scene_ports.get(_norm(c.get("name")))
            if cand and (cand.lower() + ".png") in catalog:
                p = cand
                c["portrait"] = cand      # persist the recovered name
                recovered += 1
        if not p:
            blank += 1
            continue
        fname = p.lower() + ".png"
        src = catalog.get(fname)
        if not src:
            missing += 1
            missing_names.append(p)
            continue
        shutil.copyfile(src, os.path.join(out_dir, fname))
        c["portraitFile"] = f"{game}/{fname}"
        matched += 1

    with open(chars_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{game}: {matched} portraits copied to app/portraits/{game}/, "
          f"{missing} unmatched, {blank} characters without a portrait name, "
          f"{recovered} recovered from scene actors")
    if missing_names:
        print("unmatched:", ", ".join(sorted(set(missing_names))))

if __name__ == "__main__":
    main()
