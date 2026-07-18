#!/usr/bin/env python3
"""Copy character portrait PNGs from a game's ContentPacks into app/portraits/<game>/
and set portraitFile on the entries in app/data/<game>/characters.json.

Portrait resolution: character "portrait" name (e.g. NPC_HumanFemale_Glory) maps to
<lowercase>.png searched across every ContentPacks/*/art/portraits/ dir. When the same
filename exists in several packs, the pack listed earliest in the priority list wins.

Usage: extract_portraits_game.py <ContentPacks-dir> <game> <pack1,pack2,...>
  e.g. extract_portraits_game.py ".../Dragonfall_Data/StreamingAssets/ContentPacks" dragonfall DragonfallExtended,berlin,seattle
"""
import json, os, shutil, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")

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

    matched = missing = blank = 0
    missing_names = []
    for c in data["characters"]:
        p = c.get("portrait")
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
          f"{missing} unmatched, {blank} characters without a portrait name")
    if missing_names:
        print("unmatched:", ", ".join(sorted(set(missing_names))))

if __name__ == "__main__":
    main()
