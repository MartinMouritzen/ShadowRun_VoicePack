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
from spoken_rules import mechanical, resolve_speaker_vars, they_disagreement, beats, SEG_MAX

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
# What the lab speaks for an UNSEGMENTED line, so a line that only becomes segmented
# because it is long keeps exactly the words it had before.
SPOKEN = jopt(os.path.join(ROOT, f"app/data/{GAME}/spoken_overrides.json"))

# ---------------------------------------------------------------- quoted speech in readable props
# An in-world article quotes the people it interviews. Left whole, the author impersonates every
# one of them. quote_splits.json lists, by hand, which quoted spans are actually speech and who
# says them - by hand because quotation marks alone cannot tell speech from a quoted TERM
# ("background count"), from a phrase ("Deep shit"), or from the author's own interjections inside
# someone else's answer. Splitting produces ordinary ~cN segments, and the voice for each quote
# segment is written into seg_overrides.json, which the lab and the generator already honour.
QSPLIT = {}
for _e in (jopt(os.path.join(HERE, "quote_splits.json")).get(GAME) or []):
    for _sp in _e.get("speakers", []):
        for _node, _quotes in (_sp.get("nodes") or {}).items():
            QSPLIT.setdefault((_e["char"], _e["convo"], int(_node)), []).append(
                {"voice": {"voiceId": _sp["voiceId"], "voiceName": _sp["voiceName"]},
                 "quotes": _quotes})
QUOTE_VOICES = {}          # segKey -> voice, merged into seg_overrides.json at the end

def split_quotes(cid, line, key, text):
    """[(text, voice_or_None)] for a line with hand-listed quotes; [] when it has none."""
    plan = QSPLIT.get((cid, line["c"], line["n"]))
    if not plan:
        return []
    spans = []
    for entry in plan:
        for q in entry["quotes"]:
            at = text.find(q)
            if at < 0:
                print(f"  WARN: quote not found verbatim in {key}: {q[:48]}...", file=sys.stderr)
                continue
            spans.append((at, at + len(q), entry["voice"]))
    if not spans:
        return []
    spans.sort()
    out, pos = [], 0
    for a, b, voice in spans:
        if a < pos:
            continue                      # overlapping listing; keep the first
        if text[pos:a].strip():
            out.append((text[pos:a].strip(), None))
        out.append((text[a:b].strip(), voice))
        pos = b
    if text[pos:].strip():
        out.append((text[pos:].strip(), None))
    return out

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
            if "$(" in t or they_disagreement(t, l["t"]):
                unresolved.append({"key": key, "char": ch["name"], "seg": "g0", "text": l["t"][:200]})
            result[key] = [{"who": "gm", "t": p} for p in (beats(t) or [t])]
            continue
        if "{{GM}}" not in l["t"]:
            # No narration in this node, so it was previously left unsegmented and shipped as one
            # take however long it ran. If it is long enough to be miserable in the lab, emit it as
            # beats instead. The text MUST match what the lab derives for an unsegmented line
            # (spoken_overrides > hand rewrite > mechanical), or splitting would quietly change the
            # words as well as the keys.
            base = (SPOKEN.get(key) or {}).get("spoken") or HAND.get(key) or mechanical(clean(l["t"]))
            quoted = split_quotes(ch["id"], l, key, base)
            if quoted:
                out = []
                for t_, voice in quoted:
                    for part in (beats(t_) or [t_]):
                        if voice:
                            QUOTE_VOICES[f"{key}~c{len(out)}"] = voice
                        out.append({"who": "char", "t": part})
                result[key] = out
                continue
            parts = beats(base)
            if len(parts) > 1:
                result[key] = [{"who": "char", "t": p} for p in parts]
            continue
        segs = raw_segments(l["t"])
        nchar = sum(1 for w, _ in segs if w == "char")
        out = []; ci = 0; gi = 0
        for who, raw in segs:
            if who == "gm":
                if key in HAND_SEG and f"g{gi}" in HAND_SEG[key]:
                    t = HAND_SEG[key][f"g{gi}"]
                else:
                    t = gm_text(raw, ch["name"], g)
                if "$(" in t or they_disagreement(t, raw):
                    unresolved.append({"key": key, "char": ch["name"], "seg": f"g{gi}", "text": raw.strip()[:200]})
                for part in (beats(t) or [t]):
                    out.append({"who": "gm", "t": part})
                gi += 1
            else:
                if key in HAND_SEG and f"c{ci}" in HAND_SEG[key]:
                    t = HAND_SEG[key][f"c{ci}"]
                elif nchar == 1 and key in HAND:
                    t = HAND[key]
                else:
                    t = mechanical(clean(raw))
                if "$(" in t or they_disagreement(t, raw):
                    unresolved.append({"key": key, "char": ch["name"], "seg": f"c{ci}", "text": raw.strip()[:200]})
                for part in (beats(t) or []):
                    out.append({"who": "char", "t": part})
                ci += 1
        result[key] = out

json.dump(result, open(os.path.join(ROOT, f"app/data/{GAME}/line_segments.json"), "w"), ensure_ascii=False, indent=1)

# Merge the quote voices into seg_overrides.json. Entries this script owns are tagged so it can
# rewrite its own without disturbing a per-line voice chosen by hand in the lab.
if QUOTE_VOICES or True:
    sp_path = os.path.join(ROOT, f"app/data/{GAME}/seg_overrides.json")
    segov = jopt(sp_path)
    segov = {k: v for k, v in segov.items() if not (isinstance(v, dict) and v.get("source") == "quote-split")}
    for k, v in QUOTE_VOICES.items():
        segov[k] = dict(v, source="quote-split")
    json.dump(segov, open(sp_path, "w"), ensure_ascii=False, indent=1)
    if QUOTE_VOICES:
        print(f"[{GAME}] quote splits: {len(QUOTE_VOICES)} quoted segment(s) given their speaker's voice")
multi = sum(1 for v in result.values() if sum(1 for s in v if s["who"] == "char") >= 2)
print(f"[{GAME}] segmented lines: {len(result)} ({multi} with interleaved speech); unresolved segs: {len(unresolved)}")
json.dump(unresolved, open(os.path.join(HERE, f"segs_unresolved{SUF}.json"), "w"), ensure_ascii=False, indent=1)
for u in unresolved[:15]: print(" ", u["key"], u["seg"], "|", u["char"], "|", u["text"][:100])
