#!/usr/bin/env python3
"""Package AI portraits for a Shadowrun pack.

The plugin feeds these into the game's own portrait pipeline (art/portraits/<name>.png), keyed
by the speaker's actorName, so the engine builds the atlas, thumbnail and frame itself.

Characters that already have their own portrait art in the game are skipped — those are never
replaced. Output: games/shadowrun/portraits_pack/<game>/{portraits.index, *.png}

Run: python3 build_portraits.py <dms|dragonfall|hk>
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
ROOT = os.path.join(BASE, "..", "..")          # ~/dev/voices
# Match the game's OWN portrait art aspect (native portraits are 212x278 ≈ 0.76, near 3:4).
# The dialogue frame is built for that shape and stretches the texture to fill it, so a 2:3
# source (0.667) came out horizontally squeezed. Same aspect as the native art => same, correct
# on-screen proportions. 2x the native size so HD-textures mode still looks crisp.
SIZE = (424, 556)

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def jload(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d

def main():
    game = sys.argv[1] if len(sys.argv) > 1 else "dms"
    lab_game = {"dms": "srr-dms", "dragonfall": "srr-dragonfall", "hk": "srr-hk"}[game]
    data = os.path.join(BASE, "app", "data", game)
    src = os.path.join(ROOT, "games", lab_game, "portraits_ai")
    out = os.path.join(BASE, "portraits_pack", game)
    os.makedirs(out, exist_ok=True)

    chars = jload(os.path.join(data, "characters.json"), {}).get("characters", [])
    have = jload(os.path.join(data, "portraits_ai.json"), {})
    picks = jload(os.path.join(data, "portrait_picks.json"), {})

    try:
        from PIL import Image
    except ImportError:
        print("ERROR: pillow required")
        return

    rows, conv_rows, packed, skipped = [], [], 0, 0
    for c in chars:
        cid = c.get("id")
        if cid in ("narrator", "uinarrator"):
            continue
        if c.get("portraitFile"):
            skipped += 1        # the game already gives this character a portrait
            continue
        fname = picks.get(cid) or ((have.get(cid) or {}).get("files") or [None])[0]
        if not fname:
            continue
        sp = os.path.join(src, fname)
        if not os.path.exists(sp):
            continue
        actor = norm(c.get("name"))
        if not actor:
            continue
        dst = os.path.join(out, f"srrv_{actor}.png")
        if (not os.path.exists(dst)) or os.path.getmtime(dst) < os.path.getmtime(sp):
            im = Image.open(sp).convert("RGB")
            tw, th = SIZE
            w, h = im.size
            scale = max(tw / w, th / h)
            im = im.resize((int(w * scale + 0.5), int(h * scale + 0.5)), Image.LANCZOS)
            w, h = im.size
            im = im.crop(((w - tw) // 2, 0, (w - tw) // 2 + tw, th))
            im.save(dst, "PNG", optimize=True)
        rows.append(f"{actor}\tsrrv_{actor}.png")
        # Also key by conversation GUID. The scene actor's runtime actorName often differs from
        # the name the lab derives from the conversation filename (e.g. conversation
        # "c08-s1_Planeyard_Hooker" but the scene actor is "Streetwalker"), so name matching
        # misses. The conversation GUID the lab stores per line IS what the game plays under, so
        # keying on it lets the plugin place the portrait on whoever actually speaks the line.
        guids = sorted({l.get("c") for l in c.get("lines", []) if l.get("c")})
        for g in guids:
            conv_rows.append(f"conv:{g}\tsrrv_{actor}.png")
        packed += 1

    # A conversation with two portrait-carrying speakers cannot be resolved by its GUID alone: the
    # plugin keys one portrait per conversation, so the second row silently overwrites the first and
    # BOTH speakers get whichever art sorted last. That is how the female bunraku drew the male
    # one's portrait. There is nothing to disambiguate with here, so drop the key entirely and let
    # the actorName path (which the game answers exactly) place both. Every character that loses a
    # key this way is listed, so a genuine loss of coverage is visible rather than silent.
    by_guid = {}
    for r in conv_rows:
        by_guid.setdefault(r.split("\t")[0], set()).add(r.split("\t")[1])
    ambiguous = {g for g, files in by_guid.items() if len(files) > 1}
    dropped_keys = sorted(r for r in conv_rows if r.split("\t")[0] in ambiguous)
    conv_rows = [r for r in conv_rows if r.split("\t")[0] not in ambiguous]

    with open(os.path.join(out, "portraits.index"), "w") as f:
        f.write("\n".join(sorted(rows) + sorted(conv_rows)) + "\n")

    # Drop PNGs this build no longer emits. A character that was renamed, merged away or had its
    # AI portrait dropped otherwise leaves its art in the pack forever, and the file being present
    # is exactly what lets a stale index keep serving it -- that is how a deleted "Mental Patient"
    # went on showing his face over Lorraine's dialogue.
    keep = {r.split("\t")[1] for r in rows + conv_rows}
    stale = sorted(f for f in os.listdir(out) if f.endswith(".png") and f not in keep)
    for f in stale:
        os.remove(os.path.join(out, f))

    print(f"[{game}] portrait pack: {packed} portraits, {len(conv_rows)} conversation keys, "
          f"{skipped} characters kept their own art"
          + (f"; dropped {len(stale)} orphaned file(s): {', '.join(stale)}" if stale else ""))
    if ambiguous:
        print(f"  {len(ambiguous)} conversation key(s) dropped as ambiguous (>1 speaker with art); "
              f"those speakers are placed by actorName instead:")
        for r in dropped_keys:
            print(f"    {r.split(chr(9))[0]} -> {r.split(chr(9))[1]}")

if __name__ == "__main__":
    main()
