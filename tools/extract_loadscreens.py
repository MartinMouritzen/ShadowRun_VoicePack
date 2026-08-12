#!/usr/bin/env python3
"""Extract loading-screen narration texts (SceneDef.scene_synopsis, protobuf field 22 of
scenes/*.srt.bytes; title = field 20) and MERGE them into app/data/<game>/barks.json as
Narrator entries with kind "loadscreen", keyed bark_<md5(synopsis.strip())[:16]>.

The key must match the plugin's Patch_LoadScreen, which hashes the load screen's text at runtime,
NOT the title. The title is stored alongside for the lab / prompt authoring. NOTE: the loading-screen
text is scene DATA, not part of the background image (loadingImage_* is a separate art asset).

ONE SYNOPSIS IS NOT ONE SCREEN. Several scenes store no words at all, only a story-variable
reference the game substitutes before drawing:

    haven.srt.bytes / a3_haven.srt.bytes  ->  "$(story.Global_HavenLoadingScreen)"
    hk_hub.srt.bytes / a3_hk_hub.srt.bytes -> "$(story.HK_HubLoadingText)"

and the game REWRITES those variables at the end of every mission. So Dragonfall's THE KREUZBASAR
is 22 different texts behind one synopsis, and Hong Kong's Heoi hub is 41. This script used to hash
the raw token and fill it in by guessing - "the longest string literal assigned to the variable" -
which produced one entry, with one arbitrary text, standing in for all of them. Shipped, that made
the Kreuzbasar narrate the first-return text over every later return: 21 of 22 loads reading words
that were not on the screen (reported 2026-08-12).

So a story-variable synopsis is expanded here the same way the game expands it: every distinct value
assigned to the variable becomes its OWN bark entry, keyed on that value. The plugin side matches by
running the synopsis through the game's own Utilities.TextExpansion before hashing.

The token-keyed entries the old behaviour left behind are RETIRED (removed from barks.json) and the
rekey map is written to tools/gen/loadscreen_rekey.json, because their takes are still good audio for
whichever variant they happen to hold - run tools/rekey_barks.py to carry them over.

Usage: extract_loadscreens.py <ContentPacks_dir> <game:dms|dragonfall|hk> <pack1[,pack2,...]>
Additive for real entries: existing bark entries (hand attribution, picks) are never touched."""
import glob, hashlib, json, os, re, sys

SR, GAME, PACKS = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "app", "data", GAME, "barks.json")
REKEY_OUT = os.path.join(HERE, "gen", "bark_rekey.json")   # shared with extract_extras_game.py

def bkey(text):
    return "bark_" + hashlib.md5(text.encode("utf-8")).hexdigest()[:16]

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

# "$(story.NAME)" — the hyphen is required: Hong Kong ships
# $(story.a2_Whistleblower_s1-WarpOutText), and a name-charset that misses it silently leaves the
# raw token as the text, i.e. a narrator reading a variable name aloud.
STORY_REF = re.compile(r"\$\(story\.([A-Za-z0-9_\-]+)\)")

_blobs = None
def blobs():
    """Every pack blob as (path, bytes), read once. Assignments live in the scene scripts and the
    convos alike (Hong Kong sets HK_HubLoadingText from a .convo too), so this cannot be narrowed
    to scenes. Path and bytes are carried together on purpose: pairing two separately-globbed
    lists by index is an attribution bug waiting to happen."""
    global _blobs
    if _blobs is None:
        _blobs = [(f, open(f, 'rb').read())
                  for f in sorted(glob.glob(os.path.join(SR, "**", "*.bytes"), recursive=True))]
    return _blobs

def story_values(name):
    """Every distinct string literal assigned to a story variable -> the blobs that assign it.

    The assignment is a TsNameValuePair: the variable name as field 2 (0x12) wrapping a field-4
    string (0x22), immediately followed by the value in the same shape. Scanning for the name and
    decoding the pair that follows is enough, and does not need the whole scene-script schema.
    """
    tgt, out = name.encode(), {}
    for path, b in blobs():
        for m in re.finditer(re.escape(tgt), b):
            i = m.end()
            if i >= len(b) or b[i] != 0x12:            # not an assignment's value field
                continue
            try:
                _, j = rv(b, i + 1)
                if j < len(b) and b[j] == 0x22:        # length-delimited string
                    n, k = rv(b, j + 1)
                    if 20 < n < 8000:
                        val = b[k:k + n].decode('utf-8', 'replace').strip()
                        if val:
                            out.setdefault(val, set()).add(os.path.basename(path).split('.')[0])
            except IndexError:
                pass
    return {v: sorted(s) for v, s in out.items()}

# Titles are deliberately NOT expanded. Hong Kong's hub screen titles itself
# "$(story.HK_Hub_Name)", which takes five values across the campaign (SINLESS, HEOI, REVELATIONS,
# AFTERMATH, RAYMOND BLACK) with no way to say which act a given body text belongs to. Nothing reads
# the title aloud - it is lab metadata - so a raw token there is ugly but honest, where picking one
# of the five would be the same guess this script exists to stop making.
def entry(text, title, scene, var=None, set_in=None):
    e = {"text": text, "speaker": "Narrator", "sheetId": None, "archetype": None,
         "gender": "?", "portrait": None, "nonverbal": False, "count": 1,
         "kind": "loadscreen", "title": (title or "").strip(), "scenes": [scene]}
    if var:
        # Which variable this screen reads, and which scene sets THIS value. Without it the lab
        # shows 22 near-identical "THE KREUZBASAR" narrations with no way to tell them apart.
        e["storyVar"] = var
        e["setIn"] = set_in or []
    return e

found, retired = {}, {}
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
        scene = os.path.basename(sf).split('.')[0]
        refs = set(STORY_REF.findall(syn))

        if not refs:                                    # the ordinary case: the words are right here
            key = bkey(syn)
            if key in found: found[key]["scenes"].append(scene)
            else: found[key] = entry(syn, title, scene)
            continue

        # The token key is what the OLD extractor and the OLD plugin agreed on. It is not a screen,
        # so it must not survive as one; remember it so its takes can follow the right variant.
        retired[bkey(syn)] = {"scene": scene, "synopsis": syn, "title": (title or "").strip()}

        if len(refs) > 1:
            print(f"  WARN: {scene}: synopsis references {len(refs)} story variables "
                  f"({', '.join(sorted(refs))}) — cannot enumerate, screen left unvoiced",
                  file=sys.stderr)
            continue
        var = refs.pop()
        vals = story_values(var)
        if not vals:
            print(f"  WARN: {scene}: $(story.{var}) has no resolvable value — screen left unvoiced",
                  file=sys.stderr)
            continue
        for val, set_in in vals.items():
            text = syn.replace(f"$(story.{var})", val).strip()
            key = bkey(text)
            if key in found:
                if scene not in found[key]["scenes"]: found[key]["scenes"].append(scene)
                for s in set_in:
                    if s not in found[key].get("setIn", []): found[key].setdefault("setIn", []).append(s)
            else:
                found[key] = entry(text, title, scene, var, set_in)
        print(f"  {scene}: $(story.{var}) -> {len(vals)} texts "
              f"({sum(len(v) for v in vals)} chars)")

barks = json.load(open(OUT)) if os.path.exists(OUT) else {}

# Retire the token-keyed placeholders. A retired entry whose text is one of the real variants has
# audio worth keeping, so record where it should move; one still holding the raw token never had
# anything worth keeping (it would have SPOKEN the variable name) and is simply dropped.
rekey, dropped = {}, []
for tk, info in sorted(retired.items()):
    old = barks.pop(tk, None)
    if old is None: continue
    text = (old.get("text") or "").strip()
    if text and not STORY_REF.search(text) and bkey(text) in found:
        rekey[tk] = bkey(text)
        print(f"  RETIRE {tk} -> {bkey(text)}  ({info['title']}; text is a real variant, "
              f"takes should follow)")
    else:
        dropped.append(tk)
        print(f"  RETIRE {tk} -> (dropped: text was still the raw token)")

new = [k for k in found if k not in barks]
for k in new: barks[k] = found[k]
json.dump(barks, open(OUT, "w"), ensure_ascii=False, indent=1)

if rekey or dropped:
    # Merged per key, not per game: extract_extras_game.py writes its retired popup titles into the
    # same file, and replacing the game's whole slot here would silently eat them.
    os.makedirs(os.path.dirname(REKEY_OUT), exist_ok=True)
    doc = json.load(open(REKEY_OUT)) if os.path.exists(REKEY_OUT) else {}
    slot = doc.setdefault(GAME, {})
    slot["rekey"] = dict(slot.get("rekey") or {}, **rekey)
    slot["dropped"] = sorted(set((slot.get("dropped") or []) + dropped))
    json.dump(doc, open(REKEY_OUT, "w"), ensure_ascii=False, indent=1)
    print(f"  rekey map -> tools/gen/bark_rekey.json (run tools/rekey_barks.py {GAME})")

print(f"[{GAME}] loadscreens: {len(found)} unique ({sum(len(v['text']) for v in found.values())} chars), "
      f"+{len(new)} new bark entries, -{len(retired)} token placeholders retired "
      f"(other existing entries untouched)")
