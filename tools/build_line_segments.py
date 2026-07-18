#!/usr/bin/env python3
"""Build app/data/<game>/line_segments.json: for every character line containing {{GM}} narration,
the ORDERED list of playback segments: [{who: 'gm'|'char', t: spoken_text}, ...].
Preserves interleaving (narration - speech - narration - speech). gm segments are voiced by the
narrator ($(s.*) speaker vars resolve statically via the speaker's name + char_notes gender; other
$() vars get the shared mechanical rules); char segments get the spoken_overrides treatment
(HAND single-speech rewrites win; per-segment hand fixes live in the per-game hand-segments file).

Usage: build_line_segments.py [dms|dragonfall|hk]   (default dms)
Hand files: tools/spoken_hand_rewrites.json + spoken_hand_segments.json (dms, legacy names) /
            tools/spoken_hand_rewrites_<game>.json + spoken_hand_segments_<game>.json"""
import json, re, sys, os
from spoken_rules import mechanical, resolve_speaker_vars

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    print(f"ERROR: unknown game '{GAME}'", file=sys.stderr); sys.exit(1)

ROOT = os.path.join(os.path.dirname(__file__), "..")
HERE = os.path.dirname(__file__)
SUF = "" if GAME == "dms" else f"_{GAME}"
c = json.load(open(os.path.join(ROOT, f"app/data/{GAME}/characters.json")))
def jopt(p):
    return json.load(open(p)) if os.path.exists(p) else {}
HAND = jopt(os.path.join(HERE, f"spoken_hand_rewrites{SUF}.json"))
HAND_SEG = jopt(os.path.join(HERE, f"spoken_hand_segments{SUF}.json"))
NOTES = jopt(os.path.join(ROOT, f"app/data/{GAME}/char_notes.json"))

def gender_of(cid, cname):
    n = NOTES.get(cid) or NOTES.get(cname) or {}
    return n.get("gender")

def clean(t):
    return re.sub(r'\s+', ' ', re.sub(r'\{\{/?[A-Za-z]*\}\}', '', t)).strip()

def gm_text(raw, speaker, gender):
    """Narrator-voiced segment: resolve speaker vars, then apply the shared mechanical rules to
    any remaining player vars ('He nods at $(l.him)' etc.)."""
    return mechanical(clean(resolve_speaker_vars(raw, speaker, gender)))

def raw_segments(t):
    out = []; pos = 0
    for m in re.finditer(r'\{\{GM\}\}([\s\S]*?)(?:\{\{/GM\}\}|$)', t):
        pre = t[pos:m.start()]
        if pre.strip(): out.append(["char", pre])
        out.append(["gm", m.group(1)])
        pos = m.end()
    tail = t[pos:]
    if tail.strip(): out.append(["char", tail])
    return out

result = {}
unresolved = []
for ch in c["characters"]:
    g = gender_of(ch["id"], ch["name"])
    for l in ch["lines"]:
        key = f'{l["c"]}_{l["n"]}'
        if l.get("y") == 6 and "{{GM}}" not in l["t"]:
            # GM_Speaker_Voice without markers: the whole node is narration -> narrator voices it
            if key in HAND_SEG and "g0" in HAND_SEG[key]:
                t = HAND_SEG[key]["g0"]
            else:
                t = gm_text(l["t"], ch["name"], g)
            if "$(" in t:
                unresolved.append({"key": key, "char": ch["name"], "seg": "g0", "text": l["t"][:200]})
            result[key] = [{"who": "gm", "t": t}]
            continue
        if "{{GM}}" not in l["t"]: continue
        segs = raw_segments(l["t"])
        nchar = sum(1 for w, _ in segs if w == "char")
        out = []; ci = 0; gi = 0
        for who, raw in segs:
            if who == "gm":
                if key in HAND_SEG and f"g{gi}" in HAND_SEG[key]:
                    t = HAND_SEG[key][f"g{gi}"]
                else:
                    t = gm_text(raw, ch["name"], g)
                if "$(" in t:
                    unresolved.append({"key": key, "char": ch["name"], "seg": f"g{gi}", "text": raw.strip()[:200]})
                out.append({"who": "gm", "t": t})
                gi += 1
            else:
                if key in HAND_SEG and f"c{ci}" in HAND_SEG[key]:
                    t = HAND_SEG[key][f"c{ci}"]
                elif nchar == 1 and key in HAND:
                    t = HAND[key]
                else:
                    t = mechanical(clean(raw))
                if "$(" in t:
                    unresolved.append({"key": key, "char": ch["name"], "seg": f"c{ci}", "text": raw.strip()[:200]})
                if t: out.append({"who": "char", "t": t})
                ci += 1
        result[key] = out

json.dump(result, open(os.path.join(ROOT, f"app/data/{GAME}/line_segments.json"), "w"), ensure_ascii=False, indent=1)
multi = sum(1 for v in result.values() if sum(1 for s in v if s["who"] == "char") >= 2)
print(f"[{GAME}] segmented lines: {len(result)} ({multi} with interleaved speech); unresolved segs: {len(unresolved)}")
json.dump(unresolved, open(os.path.join(HERE, f"segs_unresolved{SUF}.json"), "w"), ensure_ascii=False, indent=1)
for u in unresolved[:15]: print(" ", u["key"], u["seg"], "|", u["char"], "|", u["text"][:100])
