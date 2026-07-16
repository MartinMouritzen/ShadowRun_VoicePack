#!/usr/bin/env python3
"""Game-parameterized extractor for the three 'extras' data files:
  barks.json         combat barks ('Display Text over Actor' scene actions), keyed bark_<md5(text)[:16]>
  inspect.json       inspect one-liners (interactionRoot.inspectInteraction.inspectText in maps), keyed insp_<md5[:16]>
  scene_actors.json  {scene: [character names]} roster, junk NPCs filtered
Usage: extract_extras_game.py <ContentPacks_dir> <out_dir> <pack1[,pack2,...]>
Char sheets read from ALL packs; scenes/maps only from the listed packs.
Keys MUST match the plugin hooks (md5 hex, first 16 chars)."""
import glob, json, os, re, hashlib, sys, unicodedata

args = [a for a in sys.argv[1:] if a != "--force"]
FORCE = "--force" in sys.argv
SR   = args[0]
OUT  = args[1]
PACKS = args[2].split(",")

# Guard: refuse to clobber existing extras (DMS inspect.json has hand-added inline entries) without --force.
_existing = [f for f in ("barks.json", "inspect.json", "scene_actors.json") if os.path.exists(os.path.join(OUT, f))]
if _existing and not FORCE:
    sys.exit(f"{OUT} already has {', '.join(_existing)} — re-extracting overwrites them (and drops any "
             f"hand-added entries). Pass --force to overwrite, or delete the files first.")

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
def sub(msg, *path):
    cur = msg
    for p in path:
        found = None
        for f, wt, v in fields(cur):
            if f == p and wt == 2: found = v; break
        if found is None: return None
        cur = found
    return cur
def subs(m, fn): return [v for f, wt, v in fields(m) if f == fn and wt == 2]
def s_(b):
    if b is None: return None
    try: return b.decode('utf-8')
    except Exception: return None
def f1(m): return s_(sub(m, 1))
def md5_16(t): return hashlib.md5(t.encode('utf-8')).hexdigest()[:16]

def scene_files():
    r = []
    for p in PACKS:
        r += glob.glob(os.path.join(SR, p, "data/scenes/*.srt.bytes"))
        r += glob.glob(os.path.join(SR, p, "data/maps/*.srm.bytes"))
    return r

# 1. char sheets (all packs of this game)
sheets = {}
for pack in glob.glob(SR + "/*/data/chars/*.ch_sht.bytes"):
    data = open(pack, 'rb').read(); uid = arch = portrait = name = None
    for f, wt, v in fields(data):
        if f == 1 and wt == 2: uid = s_(v)
        elif f == 2 and wt == 2: arch = s_(v)
        elif f == 11 and wt == 2: portrait = s_(sub(v, 1)) or s_(v)
        elif f == 13 and wt == 2: name = s_(v)
    if uid: sheets[uid] = {"archetype": arch, "portrait": portrait, "name": name}

# 2. actors (with scene) from this game's scenes + maps
actors = {}; scene_roster = {}
for sf in scene_files():
    data = open(sf, 'rb').read(); scene = os.path.basename(sf).split('.')[0]
    for prop in subs(data, 4):
        idref = s_(sub(prop, 10, 1))
        if not idref: continue
        pname = s_(sub(prop, 1)); disp = s_(sub(prop, 8))
        ci = sub(prop, 100); sheet_id = None; ci_name = None; ci_portrait = None
        if ci is not None:
            for f, wt, v in fields(ci):
                if f == 2 and wt == 2: sheet_id = s_(v)
                elif f == 8 and wt == 2: ci_name = s_(v)
                elif f == 40 and wt == 2: ci_portrait = s_(sub(v, 1)) or s_(v)
        sheet = sheets.get(sheet_id or "", {})
        name = ci_name or disp or sheet.get("name") or sheet.get("archetype") or pname
        portrait = ci_portrait or sheet.get("portrait") or ""
        if idref not in actors:
            actors[idref] = {"name": name, "sheet_id": sheet_id, "portrait": portrait,
                             "archetype": sheet.get("archetype")}
        if ci is not None and name:
            scene_roster.setdefault(scene, set()).add(name)

def gender_of(portrait, name):
    p = (portrait or "") + " " + (name or "")
    if re.search(r'female', p, re.I): return "female"
    if re.search(r'male', p, re.I): return "male"
    return "?"
def is_nonverbal(t):
    core = re.sub(r'[^a-zA-Z]', '', t)
    if len(core) < 2: return True
    if re.search(r'([a-zA-Z])\1{2,}', t) and len(t.split()) <= 2: return True
    return False

# 3. barks: 'Display Text over Actor'
barks = {}
for sf in scene_files():
    data = open(sf, 'rb').read()
    for c1 in subs(data, 1):
        for c4 in subs(c1, 4):
            for act in subs(c4, 1):
                if f1(act) != "Display Text over Actor": continue
                text = None; ids = []
                def collect(m, d=0):
                    if d > 6: return
                    for f, wt, v in fields(m):
                        if wt == 2:
                            try:
                                s = v.decode('utf-8')
                                if re.fullmatch(r'[0-9a-f]{24}', s): ids.append(s)
                            except Exception: pass
                            collect(v, d + 1)
                collect(act)
                for cont in subs(act, 2):
                    for f, wt, v in fields(cont):
                        if f == 4 and wt == 2:
                            try: t = v.decode('utf-8').strip()
                            except Exception: continue
                            if len(t) >= 3 and not re.fullmatch(r'[0-9a-f]{16,32}', t): text = t
                if not text: continue
                key = "bark_" + md5_16(text)
                a = actors.get(ids[0] if ids else "", {})
                e = barks.get(key)
                if e: e["count"] += 1
                else:
                    barks[key] = {"text": text, "speaker": a.get("name") or "Unknown",
                                  "sheetId": a.get("sheet_id"), "archetype": a.get("archetype"),
                                  "gender": gender_of(a.get("portrait"), a.get("name")),
                                  "portrait": a.get("portrait"), "nonverbal": is_nonverbal(text), "count": 1}

# 4. inspects: PropInstance.interactionRoot(11).inspectInteraction(20).inspectText(3).
# Props live under field 4 in scene files but field 8 in map (.srm) files, so scan both.
inspects = {}
for sf in scene_files():
    data = open(sf, 'rb').read()
    for pfield in (4, 8):
        for prop in subs(data, pfield):
            raw = s_(sub(prop, 11, 20, 3))
            if not raw or not raw.strip() or len(raw.strip()) < 4: continue
            raw = raw.strip()
            inspects.setdefault("insp_" + md5_16(raw), {"spoken": raw})

# 5. scene_actors roster (filter junk NPCs)
JUNK = re.compile(r'^(NPC|Guest|Spectator|Patron|Customer|Bystander|Civilian|Crowd|Extra|Dancer|Guard \d|Ganger|Goon|Thug \d|Worker|Shopper|Reveler|Drone|Turret|Camera|Corpse|Body|Sarariman|Passerby)\s*\d*$', re.I)
scene_actors = {}
for sc, names in scene_roster.items():
    keep = sorted(n for n in names if n and not JUNK.match(n.strip()))
    if keep: scene_actors[sc] = keep

os.makedirs(OUT, exist_ok=True)
json.dump(barks, open(os.path.join(OUT, "barks.json"), "w"), ensure_ascii=False, indent=1)
json.dump(inspects, open(os.path.join(OUT, "inspect.json"), "w"), ensure_ascii=False, indent=1)
json.dump(scene_actors, open(os.path.join(OUT, "scene_actors.json"), "w"), ensure_ascii=False, indent=1)
from collections import Counter
spk = Counter(b["speaker"] for b in barks.values() if not b["nonverbal"])
print(f"barks: {len(barks)} unique | non-verbal: {sum(1 for b in barks.values() if b['nonverbal'])} | voiceable: {sum(1 for b in barks.values() if not b['nonverbal'])}")
print(f"inspects: {len(inspects)} | scenes with roster: {len(scene_actors)}")
print("top bark speakers:", ", ".join(f"{n}({c})" for n, c in spk.most_common(8)))
