#!/usr/bin/env python3
"""Cast a whole pack from char_notes.json, without putting the same voice in one room twice.

    Usage: cast_from_notes.py <game> [--pool main|screen|all] [--apply] [--limit N]

Casting by hand is auditioning; this is the part before that — getting every character off the
default so the lab has something to play. Each character takes the best-fitting voice from its own
char_notes suggestions (built from its bio, direction and gender), and anything recast in the lab
afterwards survives: an existing pick is never overwritten.

The one rule worth enforcing mechanically is that two characters who appear in the SAME SCENE must
not share a voice. 244 characters against 217 English voices means reuse is unavoidable, so it has
to happen where nobody can hear it — a Kowloon thug and a Heoi shopkeeper who never meet can share,
two guards in the same corridor cannot. scene_actors.json says who is where.

Message-board handles (screenSpeaker) are a separate pool, cast LAST and only against what the main
cast left: a hundred of them would otherwise eat the catalog before the crew is picked. They share
one surface rather than a scene, so the rule for them is thread-local — no two handles posting
within a few nodes of each other sound alike.
"""
import json, os, re, sys
from collections import Counter, defaultdict

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
POOL = "all"
for i, arg in enumerate(sys.argv):
    if arg == "--pool" and i + 1 < len(sys.argv):
        POOL = sys.argv[i + 1]
APPLY = "--apply" in sys.argv
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
D = os.path.join(ROOT, "app", "data", GAME)
LAB = os.path.normpath(os.path.join(ROOT, "..", "..", "lab"))


def J(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


chars = J(os.path.join(D, "characters.json"), {"characters": []})
notes = J(os.path.join(D, "char_notes.json"), {})
picks = J(os.path.join(D, "picks.json"), {})
scene_actors = J(os.path.join(D, "scene_actors.json"), {})
catalog = J(os.path.join(LAB, "magnific_voices.json"), {"voices": []})["voices"]
local = J(os.path.join(LAB, "local_voices.json"), {"voices": []}).get("voices") or []
by_vid = {v["voice_id"]: v for v in catalog + local}

cast = chars["characters"]
by_id = {c["id"]: c for c in cast}
by_name = {c["name"]: c["id"] for c in cast}

# ---------------------------------------------------------------- who shares a room with whom
# scene_actors.json records the roster under the names the SCENE files use, and Hong Kong's scenes
# name a third of their cast through a template - "$(scene.Convention_ConGoer3Name)". The characters
# get resolved by apply_hk_names.py, the roster never does (extract_extras_game.py rewrites it
# afterwards), so 263 of 465 names matched nothing and those characters had no same-scene constraint
# at all. Resolve through the same map the renamer uses.
resolve = {k.strip(): v for k, v in
           J(os.path.join(HERE, f"{GAME}_name_resolution.json"),
             J(os.path.join(HERE, "hk_name_resolution.json"), {}) if GAME == "hk" else {}).items()
           if not k.startswith("_")}


def actor_id(name):
    return by_name.get(name) or by_name.get(resolve.get(name.strip(), ""))


neighbours = defaultdict(set)
for scene, names in scene_actors.items():
    ids = [actor_id(n) for n in names]
    ids = [i for i in ids if i]
    for a in ids:
        neighbours[a].update(i for i in ids if i != a)

# Handles never appear in a scene; they appear in a THREAD. Two posters a few nodes apart are
# talking to each other, and hearing one voice answer itself is the failure this avoids.
THREAD_SPAN = 6
posts = defaultdict(list)
for c in cast:
    if not c.get("screenSpeaker"):
        continue
    for l in c["lines"]:
        posts[c["id"]].append((l["c"], l["n"]))
for a, pa in posts.items():
    for b, pb in posts.items():
        if a >= b:
            continue
        if any(ca == cb and abs(na - nb) <= THREAD_SPAN for ca, na in pa for cb, nb in pb):
            neighbours[a].add(b)
            neighbours[b].add(a)

# ---------------------------------------------------------------- scoring
def gender_of(cid):
    n = notes.get(cid) or {}
    return n.get("gender") or (by_id.get(cid) or {}).get("gender")


# When a direction names an accent, the English pool cannot supply it — there is not one
# Russian-, Japanese- or Cantonese-accented English voice in the catalog. The packs already solve
# this by casting the voice in the character's OWN language and letting v3 read English through it:
# Vlad is Ukrainian, Volker Stahl is German, the Foreign Elf is Korean. Only applied when the
# character's own note asks for it, so a Hong Kong cast does not get blanket-accented by default.
ACCENTS = {"russian": "Russian", "japanese": "Japanese", "cantonese": "Chinese",
           "mandarin": "Chinese", "chinese": "Chinese", "korean": "Korean",
           "filipino": "Filipino", "tagalog": "Filipino", "german": "German",
           "french": "French", "spanish": "Spanish", "italian": "Italian",
           "ukrainian": "Ukrainian", "polish": "Polish", "arabic": "Arabic",
           "turkish": "Turkish", "vietnamese": "Vietnamese", "indonesian": "Indonesian"}


def wanted_lang(cid):
    n = notes.get(cid) or {}
    hay = f"{n.get('direction') or ''} {n.get('bio') or ''}".lower()
    for word, lang in ACCENTS.items():
        if re.search(rf"\b{word}[- ]?(?:accent|inflect|inflected|cadence)?", hay) and word in hay:
            # "Japanese-inflected dignity" counts; "the Japanese corporation" does not.
            if re.search(rf"\b{word}[- ](?:accent|accented|inflect\w*|cadence|lilt)", hay) \
               or re.search(rf"\b{word}\b[^.]*\b(?:accent|inflect\w*|cadence|lilt)\b", hay):
                return lang
    return None


def fits(vid, cid):
    v, want = by_vid.get(vid), gender_of(cid)
    if not v:
        return False
    lang = wanted_lang(cid) or "English"
    if (v.get("lang") or "English") != lang:
        return False
    if want and v.get("gender") and v["gender"] != want and v["gender"] != "neutral":
        return False
    return True


used = Counter()
# How loudly a voice is already established: the biggest part currently using it. Reusing a voice
# is fine; reusing the crew's is not.
exposure = Counter()
for cid, p in picks.items():
    if p.get("voiceId"):
        used[p["voiceId"]] += 1
        exposure[p["voiceId"]] = max(exposure[p["voiceId"]],
                                     len((by_id.get(cid) or {}).get("lines") or []))
voice_of = {cid: p.get("voiceId") for cid, p in picks.items() if p.get("voiceId")}


def taken_nearby(vid, cid):
    return any(voice_of.get(other) == vid for other in neighbours.get(cid, ()))


def choose(cid):
    """The character's own suggestions first, then the wider catalog. None when nothing fits."""
    ranked = [s["voice_id"] for s in (notes.get(cid) or {}).get("suggestions", [])]
    ranked += [v["voice_id"] for v in catalog if v["voice_id"] not in ranked]
    # unused-and-unheard first, then unheard-but-reused, ordered by how little it has been used
    for stage in (0, 1):
        best, best_cost = None, None
        for vid in ranked:
            if not fits(vid, cid) or taken_nearby(vid, cid):
                continue
            n = used[vid]
            if stage == 0 and n:
                continue
            # Sharing is unavoidable once the catalog runs out, so it has to land on parts nobody
            # will recognise. A voice already carrying one of the leads costs far more than one
            # carrying a two-line shopkeeper: hearing Gobbet answer herself on a message board is
            # the thing this is trying to avoid.
            cost = (n, exposure[vid])
            if best is None or cost < best_cost:
                best, best_cost = vid, cost
                if stage == 0:
                    break
        if best:
            return best
    return None


def run(ids, label):
    made = []
    for cid in ids:
        if cid in picks and picks[cid].get("voiceId"):
            continue
        vid = choose(cid)
        if not vid:
            print(f"  WARN: no voice fits {by_id[cid]['name']!r}", file=sys.stderr)
            continue
        v = by_vid[vid]
        picks[cid] = {"voiceId": vid, "voiceName": v.get("name")}
        voice_of[cid] = vid
        used[vid] += 1
        exposure[vid] = max(exposure[vid], len(by_id[cid].get("lines") or []))
        made.append((cid, v.get("name")))
    reused = sum(1 for _cid, _n in made if used[voice_of[_cid]] > 1)
    print(f"[{GAME}] {label}: cast {len(made)}, {len(set(voice_of[c] for c, _ in made))} distinct "
          f"voices, {reused} sharing with a character they never meet")
    return made


size = lambda c: len(c.get("lines") or [])
main = [c["id"] for c in sorted(cast, key=size, reverse=True) if not c.get("screenSpeaker")]
screen = [c["id"] for c in sorted(cast, key=size, reverse=True) if c.get("screenSpeaker")]

made = []
if POOL in ("main", "all"):
    made += run(main, "main cast")
if POOL in ("screen", "all"):
    made += run(screen, "message-board handles")

clashes = [(by_id[a]["name"], by_id[b]["name"], voice_of[a])
           for a in voice_of for b in neighbours.get(a, ())
           if b in voice_of and a < b and voice_of[a] == voice_of[b]]
print(f"[{GAME}] same-scene/thread voice clashes: {len(clashes)}")
for c in clashes[:10]:
    print("   !", c[0], "/", c[1], "->", by_vid.get(c[2], {}).get("name"))

if APPLY:
    json.dump(picks, open(os.path.join(D, "picks.json"), "w"), ensure_ascii=False, indent=1)
    print(f"[{GAME}] wrote picks.json ({len(picks)} cast)")
else:
    print(f"[{GAME}] --apply not given, nothing written")
    for cid, name in made[:25]:
        print(f"    {by_id[cid]['name'][:34]:36s} {size(by_id[cid]):5d} lines  ->  {name}")
