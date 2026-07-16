#!/usr/bin/env python3
"""Game-parameterized conversation extractor (generalized from extract_dms.py).
Usage: extract_game.py <ContentPacks_dir> <out_dir> <pack1[,pack2,...]>
  ContentPacks_dir: the game's .../StreamingAssets/ContentPacks
  out_dir:          where to write characters.json (e.g. app/data/hk)
  packs:            comma-separated pack subdir names to extract (convos+scenes), e.g. HongKong,hk_coda
Char sheets are read from ALL packs under ContentPacks_dir; convos/scenes only from the listed packs.
Schema (ShadowrunDTO, identical across SRR/Dragonfall/Hong Kong):
  Conversation: 1 idRef, 2 ui_name, 3 nodes | Node: 2 index, 4 text, 6 nodeType, 12 sourceInSceneRef, 13 sourceWithTagInScene
  SceneDef: 4 PropInstance | PropInstance: 1 name, 7 GeneralTags, 8 displayName, 10 idRef, 11 interactionRoot, 100 character_instance
  CharacterInstance: 2 sheet_id, 8 name, 11 tags, 40 portrait, 41 bio | Char sheet: 1 uid, 2 archetype, 11 portrait, 13 name
"""
import glob, json, os, re, sys

args = [a for a in sys.argv[1:] if a != "--force"]
FORCE = "--force" in sys.argv
SR   = args[0]
OUT  = args[1]
PACKS = args[2].split(",")
HEX24 = re.compile(r'^[0-9a-f]{24}$')

# Guard: re-extracting OVERWRITES characters.json, destroying any manual attribution corrections
# layered on top (the DMS pack has hand-fixes: Tweaker split, Ghoul->Jake, Player-1, etc.).
# Refuse to clobber an existing file unless --force is given.
_out_chars = os.path.join(OUT, "characters.json")
if os.path.exists(_out_chars) and not FORCE:
    sys.exit(f"{_out_chars} already exists — re-extracting overwrites it and destroys any manual "
             f"attribution corrections. Pass --force to overwrite, or delete the file first.")

def read_varint(b, i):
    r = 0; s = 0
    while True:
        x = b[i]; i += 1
        r |= (x & 0x7f) << s
        if not x & 0x80: return r, i
        s += 7
def fields(b):
    i = 0; n = len(b)
    while i < n:
        try: tag, i = read_varint(b, i)
        except IndexError: return
        f, wt = tag >> 3, tag & 7
        if wt == 0:
            try: v, i = read_varint(b, i)
            except IndexError: return
            yield f, wt, v
        elif wt == 1: yield f, wt, b[i:i+8]; i += 8
        elif wt == 2:
            l, i = read_varint(b, i)
            if i + l > n: return
            yield f, wt, b[i:i+l]; i += l
        elif wt == 5: yield f, wt, b[i:i+4]; i += 4
        else: return
def sub(msg, *path):
    cur = msg
    for p in path:
        found = None
        for f, wt, v in fields(cur):
            if f == p and wt == 2: found = v; break
        if found is None: return None
        cur = found
    return cur
def subs(msg, fieldno): return [v for f, wt, v in fields(msg) if f == fieldno and wt == 2]
def s_(b):
    if b is None: return None
    try: return b.decode('utf-8')
    except Exception: return None
def varint_field(msg, fieldno, default=None):
    for f, wt, v in fields(msg):
        if f == fieldno and wt == 0: return v
    return default
def all_strings(msg, out, depth=0):
    if depth > 12: return
    try: items = list(fields(msg))
    except IndexError: return
    for f, wt, v in items:
        if wt == 2:
            try:
                t = v.decode('utf-8')
                if t and all(0x20 <= ord(c) or c in '\n\r\t' for c in t): out.append(t)
            except Exception: pass
            all_strings(v, out, depth + 1)

# 1. char sheets from all packs of THIS game
sheets = {}
for pack in glob.glob(SR + "/*/data/chars/*.ch_sht.bytes"):
    data = open(pack, 'rb').read()
    uid = arch = portrait = name = None
    for f, wt, v in fields(data):
        if f == 1 and wt == 2: uid = s_(v)
        elif f == 2 and wt == 2: arch = s_(v)
        elif f == 11 and wt == 2: portrait = s_(sub(v, 1)) or s_(v)
        elif f == 13 and wt == 2: name = s_(v)
    if uid: sheets[uid] = {"archetype": arch, "portrait": portrait, "name": name, "file": os.path.basename(pack)}

# 2. scenes -> actors, tags, owners
actors = {}; tag_map = {}; owner_map = {}; trigger_pairs = {}
scene_files = []
for p in PACKS:
    scene_files += glob.glob(os.path.join(SR, p, "data/scenes/*.srt.bytes"))
scene_datas = []
for sf in scene_files:
    scene = os.path.basename(sf).split('.')[0]
    data = open(sf, 'rb').read()
    scene_datas.append((scene, data))
    for prop in subs(data, 4):
        idref = s_(sub(prop, 10, 1))
        if not idref: continue
        pname = None; disp = None; tags = set()
        for f, wt, v in fields(prop):
            if f == 1 and wt == 2: pname = s_(v)
            elif f == 8 and wt == 2: disp = s_(v)
            elif f == 7 and wt == 2:
                t = s_(v)
                if t: tags.add(t)
        ci = sub(prop, 100); sheet_id = None; ci_name = None; ci_portrait = None; ci_bio = None
        if ci is not None:
            for f, wt, v in fields(ci):
                if f == 2 and wt == 2: sheet_id = s_(v)
                elif f == 8 and wt == 2: ci_name = s_(v)
                elif f == 11 and wt == 2:
                    t = s_(v)
                    if t: tags.add(t)
                elif f == 40 and wt == 2: ci_portrait = s_(sub(v, 1)) or s_(v)
                elif f == 41 and wt == 2: ci_bio = s_(v)
        sheet = sheets.get(sheet_id or "", {})
        name = ci_name or disp or sheet.get("name") or pname
        portrait = ci_portrait or sheet.get("portrait")
        actors[idref] = {"name": name, "sheet_id": sheet_id, "tags": sorted(tags),
                         "scene": scene, "propname": pname, "portrait": portrait, "bio": ci_bio}
        for t in tags:
            tag_map.setdefault((scene, t), idref); tag_map.setdefault((None, t), idref)
        conv = sub(prop, 11, 14)
        if conv is not None:
            cid = None
            for f, wt, v in fields(conv):
                if f == 1 and wt == 2: cid = s_(v)
            if cid: owner_map.setdefault(cid, idref)

START_FNS = {"Start Conversation", "Start Conversation Between Actors",
             "Assign Conversation to Actor", "Start Conversation From Actor"}
def scan_calls(msg, depth=0):
    if depth > 12: return
    try: items = list(fields(msg))
    except IndexError: return
    direct = [t for t in (s_(v) for f, wt, v in items if wt == 2) if t]
    if any(t in START_FNS for t in direct):
        strs = []; all_strings(msg, strs)
        hexes = [t for t in strs if HEX24.match(t)]
        convo_hits = sorted(set(h for h in hexes if h not in actors))
        actor_hits = sorted(set(h for h in hexes if h in actors))
        if len(actor_hits) == 1 and len(convo_hits) == 1:
            trigger_pairs.setdefault(convo_hits[0], actor_hits[0])
    for f, wt, v in items:
        if wt == 2: scan_calls(v, depth + 1)
for scene, data in scene_datas:
    for trig in subs(data, 1): scan_calls(trig)

import unicodedata
def norm(t):
    # NFKD-fold accents so e.g. "Gaichû" and "Gaichu" collapse to the same key
    t = unicodedata.normalize('NFKD', t or '')
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', t.lower())
name_index = {}
for aid, a in actors.items():
    n = norm(a.get("name"))
    if n and len(n) >= 4: name_index.setdefault(n, aid)

# 3. conversations
GM_TYPES = {4}; INPUT_TYPES = {7, 8}
chars_out = {}
narrator = {"id": "narrator", "name": "Narrator (GM)", "portrait": None, "lines": []}
unattributed = {"id": "unattributed", "name": "(Unassigned)", "portrait": None, "lines": []}
stats = {"nodes": 0, "attributed": 0, "narrator": 0, "input": 0, "empty": 0, "unattributed": 0}
def actor_key(aid):
    a = actors.get(aid)
    if not a: return None
    n = norm(a.get("name"))
    return ("name_" + n) if n else (a["sheet_id"] or ("actor_" + aid))
def add_line(bucket_key, aid, convo_id, convo_name, node_idx, text, ntype):
    rec = {"c": convo_id, "n": node_idx, "cn": convo_name, "t": text}
    if ntype != 1: rec["y"] = ntype
    if bucket_key == "narrator": narrator["lines"].append(rec); return
    if bucket_key is None: unattributed["lines"].append(rec); return
    if bucket_key not in chars_out:
        a = actors.get(aid) or {}; sheet = sheets.get(a.get("sheet_id") or "", {})
        nm = a.get("name") or sheet.get("name") or bucket_key
        chars_out[bucket_key] = {"id": bucket_key, "name": nm, "portrait": a.get("portrait") or sheet.get("portrait"),
                                 "archetype": sheet.get("archetype"), "bio": a.get("bio"), "lines": []}
    elif not chars_out[bucket_key].get("portrait"):
        chars_out[bucket_key]["portrait"] = (actors.get(aid) or {}).get("portrait")
    chars_out[bucket_key]["lines"].append(rec)

convo_files = []
for p in PACKS:
    convo_files += glob.glob(os.path.join(SR, p, "data/convos/*.convo.bytes"))
for cf in convo_files:
    data = open(cf, 'rb').read()
    convo_id = s_(sub(data, 1, 1)) or os.path.basename(cf).split('.')[0]
    convo_name = None
    for f, wt, v in fields(data):
        if f == 2 and wt == 2: convo_name = s_(v)
    scene_prefix = (convo_name or "").split('_')[0].lower()
    default_owner = owner_map.get(convo_id) or trigger_pairs.get(convo_id)
    for node in subs(data, 3):
        stats["nodes"] += 1
        idx = varint_field(node, 2, None); ntype = varint_field(node, 6, 1)
        text = None; src_ref = None; src_tag = None
        for f, wt, v in fields(node):
            if f == 4 and wt == 2: text = s_(v)
            elif f == 12 and wt == 2: src_ref = s_(sub(v, 1))
            elif f == 13 and wt == 2: src_tag = s_(v)
        if not text or not text.strip(): stats["empty"] += 1; continue
        if ntype in GM_TYPES or ntype in INPUT_TYPES:
            stats["narrator" if ntype in GM_TYPES else "input"] += 1
            add_line("narrator", None, convo_id, convo_name, idx, text, ntype); continue
        aid = None
        if src_ref and src_ref in actors: aid = src_ref
        elif src_tag:
            hit = None
            for (sc, t), a in tag_map.items():
                if t == src_tag and sc and sc.lower().startswith(scene_prefix): hit = a; break
            aid = hit or tag_map.get((None, src_tag))
        if aid is None and convo_name:
            tail = norm(re.sub(r'^c?\d+-?s?\d*[_ ]?', '', re.sub(r'^a\d+_', '', convo_name), flags=re.I))
            tail = re.sub(r'\d+$', '', tail)
            if tail and len(tail) >= 4:
                best = None
                for n, a in name_index.items():
                    if n in tail or tail in n:
                        if best is None or len(n) > len(best[0]): best = (n, a)
                if best: aid = best[1]
        if aid is None and default_owner: aid = default_owner
        if aid:
            stats["attributed"] += 1; add_line(actor_key(aid), aid, convo_id, convo_name, idx, text, ntype)
        else:
            stats["unattributed"] += 1; add_line(None, None, convo_id, convo_name, idx, text, ntype)

merged = {}
for c in chars_out.values():
    k = norm(c["name"]) or c["id"]
    if k in merged:
        m = merged[k]; m["lines"].extend(c["lines"])
        m["portrait"] = m["portrait"] or c["portrait"]; m["archetype"] = m["archetype"] or c["archetype"]
    else: merged[k] = c
result = sorted(merged.values(), key=lambda c: -len(c["lines"]))
os.makedirs(OUT, exist_ok=True)
out = {"characters": result, "narrator": narrator, "unattributed": unattributed, "stats": stats,
       "sheets_indexed": len(sheets), "actors_indexed": len(actors)}
json.dump(out, open(os.path.join(OUT, "characters.json"), "w"), ensure_ascii=False, indent=1)
print(json.dumps(stats))
print(f"characters: {len(result)}, narrator lines: {len(narrator['lines'])}, unattributed: {len(unattributed['lines'])}")
