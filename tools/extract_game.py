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

from speaker_registry import load_speaker_registry, resolve_node_actor

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

def pname_(v):
    """A portrait NAME out of a portrait field, or None.

    The field is a nested message holding the name in field 1. When a character instance leaves it
    EMPTY the nested bytes are b"\n\x00" - field 1, length zero - and the old
    `s_(sub(v,1)) or s_(v)` decoded that raw wrapper into the literal string "\n\x00". Being
    truthy, it then shadowed the character SHEET's real portrait at `ci_portrait or sheet[...]`,
    so 82 of Dragonfall's characters were recorded as having no portrait while the game happily
    drew one - Marta among them. Anything that is not a plausible asset name is None, so the
    fallback to the sheet works as intended."""
    # ONLY field 1. Decoding the wrapper itself as a fallback does not just yield the "\n\x00"
    # garbage - when field 1 is absent it returns whatever bytes sit there, which handed a
    # Waitress and a printed manifesto the cyberzombie's portrait. No name here means no name;
    # the caller falls back to the character sheet, which is the correct source.
    t = (s_(sub(v, 1)) or "").strip()
    return t if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_\- ]*", t or "") else None
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
        elif f == 11 and wt == 2: portrait = pname_(v)
        elif f == 13 and wt == 2: name = s_(v)
    if uid: sheets[uid] = {"archetype": arch, "portrait": portrait, "name": name, "file": os.path.basename(pack)}

# Party-slot placeholders. The editor's player-spawn props (system_spawner_playerSpawner) and the
# Matrix player icon (chars_icon_playerIcon) stand in for whoever the RUNTIME drops into that party
# slot; in game the dialogue UI shows that party member's real name and portrait. Designers
# sometimes rename the prop to the character scripted into the slot (DMS c10-s2's spawner is
# literally "Shannon Half-Sky", and its lines attribute correctly), but usually leave the editor
# default -- "Player One (Shaman)", "Player 1", "Player Character 1", "New Actor". Taking that
# default literally invents a character that never speaks in game, and it then gets cast and voiced,
# so the wrong voice ships (the DMS c10-s1 "Player One (Shaman)" line, actually Shannon's). A
# defaulted slot is therefore barred from being a speaker at all: no tag lookup, no conversation
# ownership, no name-index match, and an explicit node reference to one falls through to the
# unattributed bucket for hand-attribution rather than being guessed at.
PLACEHOLDER_PROP = re.compile(r'system_spawner_playerSpawner|chars_icon_playerIcon', re.I)
def is_placeholder(a):
    if not a or not PLACEHOLDER_PROP.search(a.get("propname") or ""): return False
    n = (a.get("name") or "").strip().lower()
    return (not n) or n.startswith("player") or n == "new actor"

# 2. scenes -> actors, tags, owners
actors = {}; tag_map = {}; owner_map = {}; owner_candidates = {}; trigger_pairs = {}
scene_files = []
for p in PACKS:
    scene_files += glob.glob(os.path.join(SR, p, "data/scenes/*.srt.bytes"))
scene_files.sort()  # deterministic "first-prop wins" owner resolution across filesystems
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
                elif f == 40 and wt == 2: ci_portrait = pname_(v)
                elif f == 41 and wt == 2: ci_bio = s_(v)
        sheet = sheets.get(sheet_id or "", {})
        name = ci_name or disp or sheet.get("name") or pname
        portrait = ci_portrait or sheet.get("portrait")
        actors[idref] = {"name": name, "sheet_id": sheet_id, "tags": sorted(tags),
                         "scene": scene, "propname": pname, "portrait": portrait, "bio": ci_bio}
        if is_placeholder(actors[idref]): continue   # party-slot stand-in: never a speaker (see above)
        for t in tags:
            tag_map.setdefault((scene, t), idref); tag_map.setdefault((None, t), idref)
        conv = sub(prop, 11, 14)
        if conv is not None:
            cid = None
            for f, wt, v in fields(conv):
                if f == 1 and wt == 2: cid = s_(v)
            if cid:
                owner_map.setdefault(cid, idref)
                lst = owner_candidates.setdefault(cid, [])
                if idref not in lst: lst.append(idref)

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
        actor_hits = sorted(set(h for h in hexes if h in actors and not is_placeholder(actors[h])))
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

# Hong Kong (and some later content packs) carries a conversation speaker registry in addition to
# scene actors. Node field 15 points into it, but it is active ONLY with field 14's override flag.
# The current HK packs ship 890 field-15 values and zero active field-14 flags: every one is dormant
# editor state. Registry records are therefore gated on the flag below and accepted only when name
# or portrait resolves to one existing actor. Screen furniture such as "Terminal" and "Datastore"
# retains the established fallback behavior.
speaker_registry = load_speaker_registry(SR, PACKS, fields, s_)
name_index = {}
for aid, a in actors.items():
    if is_placeholder(a): continue   # else "a1_Intro_s2-AudranSeesThePlayer" matches the spawner "Player", not Audran
    n = norm(a.get("name"))
    if n and len(n) >= 4: name_index.setdefault(n, aid)

# Owner disambiguation for ACTORLESS nodes. A conversation can be bound to MORE than one scene
# actor (e.g. a crime scene both the cop and the questioned NPC can trigger). owner_map keeps the
# first-parsed prop, which is arbitrary; when the true default speaker is a different co-owner,
# every actorless node lands on the wrong character -- the McKlusky/Shannon "Planeyard_Shaman" bug.
# When there are multiple DISTINCT-named candidates, disambiguate by matching the conversation
# name's descriptive tail against each candidate's NAME (and Story_* sheet tail) tokens. Generic
# archetype sheets (Lonestar_Lv1_Captain, BaseCivilian, Guard-*) never contribute tokens: they are
# roles, not identities, and would collide. No confident match -> keep the first candidate (old
# behaviour, so same-role co-owners like clone variants are unaffected) and record a warning.
_OWNER_STOP = {"story", "the", "and", "new", "actor", "npc", "base"}
def _otoks(t):
    t = unicodedata.normalize('NFKD', t or '')
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r'([a-z])([A-Z])', r'\1 \2', t)
    return set(p for p in re.split(r'[^a-z0-9]+', t.lower()) if len(p) >= 3 and p not in _OWNER_STOP)
def _cand_tokens(aid):
    a = actors.get(aid) or {}
    toks = _otoks(a.get("name"))
    sid = a.get("sheet_id") or ""
    if sid.lower().startswith("story"):        # named story character -> sheet tail is identity
        toks |= _otoks(re.sub(r'^[Ss]tory[_-]?', '', sid))
    return toks
owner_warnings = []
def resolve_owner(convo_id, convo_name):
    cands = owner_candidates.get(convo_id) or ([owner_map[convo_id]] if convo_id in owner_map else [])
    if not cands: return None
    if len(cands) == 1: return cands[0]
    if len({norm((actors.get(a) or {}).get("name")) for a in cands}) == 1:
        return cands[0]                        # co-owners share a name (variants) -> not ambiguous
    tail = re.sub(r'_?\d+$', '', re.sub(r'^c?\d+-?s?\d*[_ ]?', '',
                  re.sub(r'^a\d+_', '', convo_name or '', flags=re.I), flags=re.I))
    nt = _otoks(tail)
    scored = sorted(((len(_cand_tokens(a) & nt), a) for a in cands), key=lambda s: -s[0])
    if scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    owner_warnings.append((convo_id, convo_name, [(actors.get(a) or {}).get("name") for a in cands]))
    return cands[0]

# 3. conversations
# Type 6 is ConversationNodeType_GM_Speaker_Voice: narrator prose displayed alongside a character
# identity/portrait. It is still narrator audio and must not inherit the conversation owner.
GM_TYPES = {4, 6}; INPUT_TYPES = {7, 8}
chars_out = {}
narrator = {"id": "narrator", "name": "Narrator (GM)", "portrait": None, "lines": []}
unattributed = {"id": "unattributed", "name": "(Unassigned)", "portrait": None, "lines": []}
stats = {"nodes": 0, "attributed": 0, "narrator": 0, "input": 0, "empty": 0, "unattributed": 0,
         "placeholder": 0}
placeholder_nodes = []
name_vs_owner = []   # convo-name match overruled by the conversation's own owner
def actor_key(aid):
    a = actors.get(aid)
    if not a: return None
    n = norm(a.get("name"))
    return ("name_" + n) if n else (a["sheet_id"] or ("actor_" + aid))
def add_line(bucket_key, aid, convo_id, convo_name, node_idx, text, ntype, attribution):
    rec = {"c": convo_id, "n": node_idx, "cn": convo_name, "t": text,
           "attribution": attribution}
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
    default_owner = resolve_owner(convo_id, convo_name) or trigger_pairs.get(convo_id)
    for node in subs(data, 3):
        stats["nodes"] += 1
        idx = varint_field(node, 2, None); ntype = varint_field(node, 6, 1)
        text = None; src_ref = None; src_tag = None; override_speaker = False; speaker_uid = None
        for f, wt, v in fields(node):
            if f == 4 and wt == 2: text = s_(v)
            elif f == 12 and wt == 2: src_ref = s_(sub(v, 1))
            elif f == 13 and wt == 2: src_tag = s_(v)
            elif f == 14 and wt == 0: override_speaker = bool(v)
            elif f == 15 and wt == 2: speaker_uid = s_(v)
        if not text or not text.strip(): stats["empty"] += 1; continue
        if ntype in GM_TYPES or ntype in INPUT_TYPES:
            stats["narrator" if ntype in GM_TYPES else "input"] += 1
            provenance = "gm-node-type" if ntype in GM_TYPES else "input-node-type"
            add_line("narrator", None, convo_id, convo_name, idx, text, ntype, provenance); continue
        if src_ref and src_ref in actors and is_placeholder(actors[src_ref]):
            # explicit reference to a party slot: the speaker is runtime party state, not this prop
            placeholder_nodes.append((convo_name or convo_id, idx, actors[src_ref].get("name")))
            stats["unattributed"] += 1; stats["placeholder"] += 1   # placeholder is a subset of unattributed
            add_line(None, None, convo_id, convo_name, idx, text, ntype,
                     "party-slot-placeholder"); continue

        def lookup_tag(tag):
            hit = None
            for (sc, t), a in tag_map.items():
                if t == tag and sc and sc.lower().startswith(scene_prefix): hit = a; break
            return hit or tag_map.get((None, tag))

        # Explicit node source > active speaker override (fields 14+15) > descriptive/owner
        # fallback. Field 15 by itself is stale editor state on many HK nodes; it is only meaningful
        # when the DTO's field-14 override flag is true. The override is intentionally consulted
        # only after the placeholder guard: a runtime party slot is not made static merely because
        # the editor happened to leave a speaker portrait selected.
        aid, provenance = resolve_node_actor(
            src_ref, src_tag, override_speaker, speaker_uid, actors, lookup_tag,
            speaker_registry, norm)
        if aid is None and convo_name:
            tail = norm(re.sub(r'^c?\d+-?s?\d*[_ ]?', '', re.sub(r'^a\d+_', '', convo_name), flags=re.I))
            tail = re.sub(r'\d+$', '', tail)
            if tail and len(tail) >= 4:
                best = None
                for n, a in name_index.items():
                    if n in tail or tail in n:
                        if best is None or len(n) > len(best[0]): best = (n, a)
                # The conversation name is a designer's FILE label, not a cast list. It is often
                # descriptive of the role ("..._AcolyteConversationsHub") while the actor the
                # designer actually bound the conversation to is a specific, differently-named NPC
                # (Sister Sally). It can also match a same-named but UNRELATED actor in another
                # scene: "c10-s2_PlaneyardReturn_Spirit" matched a "Spirit" prop standing in an
                # apartment block two chapters earlier, and 17 lines of the Forgotten Souls'
                # dialogue were filed under it.
                #
                # The owner is the better answer in BOTH cases: it is a real actor in this scene,
                # placed by the designer to run this conversation. So a convo-name match only wins
                # when there is no owner to lose to. An earlier version let an IN-SCENE name match
                # beat the owner, on the theory that such a name must be pointing at that specific
                # actor; it isn't. That is what filed Sister Sally's and Brother Mike's dialogue
                # under a bystander "Acolyte" prop, merging a woman and a man into one character
                # who was then cast with a single voice and given a single (male) portrait.
                # Verified fresh-vs-fresh over DMS: preferring the owner moves exactly those two
                # conversations plus c17-s1_JakeSensesGhouls ("Ghoul" -> Jake Armitage, which was
                # already known to need a hand-fix), and nothing else.
                if best and not default_owner:
                    aid = best[1]
                    provenance = "conversation-name"
                elif best and best[1] != default_owner:
                    name_vs_owner.append((convo_name or convo_id, actors[best[1]]["name"],
                                          actors[best[1]]["scene"], actors[default_owner]["name"]))
        if aid is None and default_owner:
            aid = default_owner
            provenance = "conversation-owner"
        if aid:
            stats["attributed"] += 1
            add_line(actor_key(aid), aid, convo_id, convo_name, idx, text, ntype, provenance)
        else:
            stats["unattributed"] += 1
            add_line(None, None, convo_id, convo_name, idx, text, ntype, "unresolved")

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
if name_vs_owner:
    seen = sorted(set(name_vs_owner))
    print(f"NOTE: {len(name_vs_owner)} node(s) in {len(seen)} conversation(s) had a "
          f"convo-name match overruled by the conversation owner:", file=sys.stderr)
    for cn, nm, sc, owner in seen:
        print(f"  {cn}: name-match {nm!r} (scene {sc}) -> owner {owner!r}", file=sys.stderr)
if placeholder_nodes:
    print(f"NOTE: {len(placeholder_nodes)} node(s) point at a party-slot placeholder prop -> "
          f"unattributed (hand-attribute these; the game shows the real party member):", file=sys.stderr)
    for cn, idx, nm in placeholder_nodes:
        print(f"  {cn} n={idx}  slot={nm!r}", file=sys.stderr)
if owner_warnings:
    print(f"WARN: {len(owner_warnings)} multi-owner convo(s) with no confident primary NPC (kept first owner):",
          file=sys.stderr)
    for cid, cn, names in owner_warnings:
        print(f"  {cn or cid}: candidates={names}", file=sys.stderr)
