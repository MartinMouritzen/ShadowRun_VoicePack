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
import variants
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
            # convo can sit on the entry or on the speaker: a news prop holds several articles,
            # each its own conversation, and one source is only quoted within one of them.
            QSPLIT.setdefault((_e["char"], _sp.get("convo") or _e.get("convo"), int(_node)), []).append(
                {"voice": {"voiceId": _sp["voiceId"], "voiceName": _sp["voiceName"]},
                 "quotes": _quotes})
QUOTE_VOICES = {}          # segKey -> voice, merged into seg_overrides.json at the end

# ---------------------------------------------------------------- several people in one screen
# A Shadowland thread puts three posters in one node, and a job negotiation puts both sides of the
# call in one. tools/screen_splits_<game>.json (build_screen_splits.py) already knows who says what,
# in order, so those segments are built STRAIGHT from the plan rather than by locating each span in
# the spoken text the way split_quotes() does: that search fails to a WARN and silently collapses
# the node back to a single voice, which is invisible in the lab.
SCREEN_INLINE = {}
_sp = os.path.join(HERE, f"screen_splits_{GAME}.json")
if os.path.exists(_sp):
    SCREEN_INLINE = json.load(open(_sp)).get("inline") or {}
SCREEN_PEOPLE = {p["id"]: p for p in
                 (jopt(os.path.join(HERE, f"screen_speakers_{GAME}.json")).get("people") or {}).values()}
PICKS = jopt(os.path.join(ROOT, f"app/data/{GAME}/picks.json"))


def screen_voice(pid):
    """The voice for a person in a shared node: their cast pick, else the hand file's choice.

    Preferring the pick means recasting in the lab actually reaches these segments on the next
    build. Someone who only ever appears inside a shared node has no cast entry at all, and falls
    back to the voice named alongside them in screen_speakers_<game>.json."""
    p = PICKS.get(pid) or SCREEN_PEOPLE.get(pid) or {}
    if p.get("voiceId"):
        return {"voiceId": p["voiceId"], "voiceName": p.get("voiceName")}
    return None

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

def derive(raw_line, ch, g, key, line, record=True, bypass=False):
    """The segment list for one node's raw text. Factored out so the variant pass can re-derive
    the SAME way with template variables substituted, rather than reimplementing the rules."""
    out = []
    if record and not bypass and key in SCREEN_INLINE:
        missing = []
        for part in SCREEN_INLINE[key]:
            t = mechanical(clean(part["text"]))
            if "$(" in t or they_disagreement(t, part["text"]):
                unresolved.append({"key": key, "char": part["name"], "seg": f"c{len(out)}",
                                   "text": part["text"][:200]})
            voice = screen_voice(part["id"])
            if not voice:
                missing.append(part["name"])
            for beat in (beats(t) or [t]):
                if voice:
                    QUOTE_VOICES[f"{key}~c{len(out)}"] = voice
                out.append({"who": "char", "t": beat})
        if missing:
            print(f"  WARN: {key} has no voice for {', '.join(sorted(set(missing)))} — those "
                  f"segments keep the container's voice", file=sys.stderr)
        return out
    if line.get("y") == 6 and "{{GM}}" not in raw_line:
        # GM_Speaker_Voice without markers: the whole node is narration -> narrator voices it
        if not bypass and key in HAND_SEG and "g0" in HAND_SEG[key]:
            t = HAND_SEG[key]["g0"]
        else:
            t = gm_text(raw_line, ch["name"], g)
        if record and ("$(" in t or they_disagreement(t, raw_line)):
            unresolved.append({"key": key, "char": ch["name"], "seg": "g0", "text": raw_line[:200]})
        return [{"who": "gm", "t": p} for p in (beats(t) or [t])]
    if "{{GM}}" not in raw_line:
        # No narration in this node, so it was previously left unsegmented and shipped as one
        # take however long it ran. If it is long enough to be miserable in the lab, emit it as
        # beats instead. The text MUST match what the lab derives for an unsegmented line
        # (spoken_overrides > hand rewrite > mechanical), or splitting would quietly change the
        # words as well as the keys.
        base = (None if bypass else ((SPOKEN.get(key) or {}).get("spoken") or HAND.get(key))) \
               or mechanical(clean(raw_line))
        quoted = split_quotes(ch["id"], dict(line, t=raw_line), key, base) if record else []
        if quoted:
            for t_, voice in quoted:
                for part in (beats(t_) or [t_]):
                    if voice:
                        QUOTE_VOICES[f"{key}~c{len(out)}"] = voice
                    out.append({"who": "char", "t": part})
            return out
        parts = beats(base)
        return [{"who": "char", "t": p} for p in parts] if len(parts) > 1 else []
    segs = raw_segments(raw_line)
    nchar = sum(1 for w, _ in segs if w == "char")
    ci = gi = 0
    for who, raw in segs:
        if who == "gm":
            if not bypass and key in HAND_SEG and f"g{gi}" in HAND_SEG[key]:
                t = HAND_SEG[key][f"g{gi}"]
            else:
                t = gm_text(raw, ch["name"], g)
            if record and ("$(" in t or they_disagreement(t, raw)):
                unresolved.append({"key": key, "char": ch["name"], "seg": f"g{gi}", "text": raw.strip()[:200]})
            for part in (beats(t) or [t]):
                out.append({"who": "gm", "t": part})
            gi += 1
        else:
            if not bypass and key in HAND_SEG and f"c{ci}" in HAND_SEG[key]:
                t = HAND_SEG[key][f"c{ci}"]
            elif not bypass and nchar == 1 and key in HAND:
                t = HAND[key]
            else:
                t = mechanical(clean(raw))
            if record and ("$(" in t or they_disagreement(t, raw)):
                unresolved.append({"key": key, "char": ch["name"], "seg": f"c{ci}", "text": raw.strip()[:200]})
            for part in (beats(t) or []):
                out.append({"who": "char", "t": part})
            ci += 1
    return out

for ch in c["characters"]:
    g = gender_of(ch["id"], ch["name"])
    for l in ch["lines"]:
        key = f'{l["c"]}_{l["n"]}'
        segs_out = derive(l["t"], ch, g, key, l)
        if segs_out:
            result[key] = segs_out

# ---------------------------------------------------------------- template-variable variants
# A line like "Greetings, young $(l.race)." is authored once and displayed five ways. The rewrite
# layer used to dodge those (spoken_overrides rephrased the sentence so the word never had to be
# said), which is why an ork player never heard "ork". Here each such line is ALSO derived once per
# value, so the pack can ship a clip per variant and the plugin can play the matching one. Anything
# open-ended - the player's typed name, a counter, a date - has no closed value set and keeps its
# single generic take exactly as before.
#
# Overrides are deliberately bypassed for these lines: the override IS the dodge, so honouring it
# would produce five identical clips that all avoid the word.
CONTENT_PACKS = os.environ.get("SRR_CONTENT_PACKS", "")
SCENE_SETS = {}
if CONTENT_PACKS and os.path.isdir(CONTENT_PACKS):
    for _tok in ("scene.cafespecial", "scene.str_redorgreen"):
        _v = variants.scan_scene_values(CONTENT_PACKS, _tok)
        if _v:
            SCENE_SETS[_tok] = _v
else:
    # Loudly, because the failure is otherwise invisible and durable: without the scene blobs the
    # scene-string axes simply do not exist, every line and inspect that varies only on one of them
    # drops out of variants.json, and any variant takes already recorded for it become unreachable -
    # the pack then ships NOTHING for that line, not even the generic clip. That is exactly how the
    # seven $(scene.CafeSpecial) clips for "The special today is a ..." went silent.
    print("  WARNING: SRR_CONTENT_PACKS is not set to a ContentPacks directory — the scene-string "
          "variant axes (CafeSpecial, str_RedOrGreen) will be DROPPED from variants.json, which "
          "strands any variant takes already recorded for them. Set it and re-run.", file=sys.stderr)

def seg_keys_for(key, segs):
    """Segment keys in playback order - the same rule lab/spoken.py's segment_plan() uses."""
    nchar = sum(1 for s in segs if s["who"] == "char")
    out, gi, ci = [], 0, 0
    for s in segs:
        if s["who"] == "gm":
            out.append(f"{key}~g{gi}"); gi += 1
        else:
            out.append(key if nchar == 1 else f"{key}~c{ci}"); ci += 1
    return out

var_out, var_skipped, var_bypassed, var_dropped = {}, [], 0, []
for ch in c["characters"]:
    g = gender_of(ch["id"], ch["name"])
    for l in ch["lines"]:
        key = f'{l["c"]}_{l["n"]}'
        ax = variants.axes(l["t"], SCENE_SETS)
        if not ax:
            continue
        base_segs = result.get(key) or derive(l["t"], ch, g, key, l, record=False, bypass=True)
        if not base_segs:
            base_segs = [{"who": "char", "t": mechanical(clean(l["t"]))}]
        base_keys = seg_keys_for(key, base_segs)
        if (SPOKEN.get(key) or HAND.get(key) or HAND_SEG.get(key)):
            var_bypassed += 1
        per_seg = {}
        for vid, binding in variants.combos(ax, SCENE_SETS):
            segs_v = derive(variants.render(l["t"], binding, SCENE_SETS), ch, g, key, l,
                            record=False, bypass=True)
            if not segs_v:
                segs_v = [{"who": "char",
                           "t": mechanical(clean(variants.render(l["t"], binding, SCENE_SETS)))}]
            if len(segs_v) != len(base_segs):
                # Substitution changed how the line splits into beats, so the keys would not line
                # up with the generic take. Report rather than ship a mismatched clip.
                var_skipped.append({"key": key, "variant": vid,
                                    "beats": [len(base_segs), len(segs_v)]})
                continue
            for sk, sv in zip(base_keys, segs_v):
                per_seg.setdefault(sk, {})[vid] = sv["t"]
        for sk, vs in per_seg.items():
            # Only worth shipping where the words actually differ between variants.
            if len(set(vs.values())) <= 1:
                continue
            # Bypassing the override also discarded whatever dodge it applied to an UNBOUNDED
            # variable in the same sentence ("$(l.name) went to the trouble... let him do the
            # honors"). Voicing that would read the token aloud, so the segment keeps its generic
            # dodged take and simply gets no variants.
            if any(variants.VAR_RE.search(t) for t in vs.values()):
                var_dropped.append(sk)
                continue
            var_out[sk] = {"axes": sorted(ax), "v": vs}
# Inspect one-liners are keyed by a hash of their text, not by a node id, so their variants are
# carried the same way: one entry per value, and the pack emits a key per RESOLVED text so the
# plugin can simply hash what the game is about to display.
_insp_path = os.path.join(ROOT, f"app/data/{GAME}/inspect.json")
if os.path.exists(_insp_path):
    for _k, _e in json.load(open(_insp_path)).items():
        _t = _e.get("spoken") if isinstance(_e, dict) else _e
        _ax = variants.axes(_t or "", SCENE_SETS)
        if not _ax:
            continue
        _v = {vid: variants.render(_t, b, SCENE_SETS) for vid, b in variants.combos(_ax, SCENE_SETS)}
        if len(set(_v.values())) > 1 and not any(variants.VAR_RE.search(x) for x in _v.values()):
            var_out[_k] = {"axes": sorted(_ax), "v": _v, "hashed": True}

json.dump({"_scene_sets": SCENE_SETS, "segments": var_out},
          open(os.path.join(ROOT, f"app/data/{GAME}/variants.json"), "w"),
          ensure_ascii=False, indent=1)
_clips = sum(len(v["v"]) - 1 for v in var_out.values())
print(f"[{GAME}] variants: {len(var_out)} segments vary, {_clips} extra clips"
      + (f", {var_bypassed} bypassed a dodge-rewrite" if var_bypassed else "")
      + (f", {len(var_skipped)} skipped (beat mismatch)" if var_skipped else "")
      + (f", {len(var_dropped)} left generic (unbounded var in the same sentence)" if var_dropped else ""))

# sort_keys, because the insertion order here is not stable: the quote-split and screen-split passes
# add their keys after the main walk, so a re-run with NO content change still rewrote the whole file
# in a different order. That churns a 4,500-entry diff for nothing and, worse, flips the file's sha1 —
# which is what dupes.json fingerprints, so a no-op rebuild reported the dedup as stale. Segment
# ORDER inside each value is what matters for playback and is untouched by this.
json.dump(result, open(os.path.join(ROOT, f"app/data/{GAME}/line_segments.json"), "w"),
          ensure_ascii=False, indent=1, sort_keys=True)

# Merge the quote voices into seg_overrides.json. Entries this script owns are tagged so it can
# rewrite its own without disturbing a per-line voice chosen by hand in the lab.
if QUOTE_VOICES or True:
    sp_path = os.path.join(ROOT, f"app/data/{GAME}/seg_overrides.json")
    segov = jopt(sp_path)
    segov = {k: v for k, v in segov.items()
             if not (isinstance(v, dict) and v.get("source") in ("quote-split", "screen-split"))}
    for k, v in QUOTE_VOICES.items():
        segov[k] = dict(v, source="screen-split" if k.split("~")[0] in SCREEN_INLINE else "quote-split")
    json.dump(segov, open(sp_path, "w"), ensure_ascii=False, indent=1, sort_keys=True)
    if QUOTE_VOICES:
        print(f"[{GAME}] quote splits: {len(QUOTE_VOICES)} quoted segment(s) given their speaker's voice")
multi = sum(1 for v in result.values() if sum(1 for s in v if s["who"] == "char") >= 2)
print(f"[{GAME}] segmented lines: {len(result)} ({multi} with interleaved speech); unresolved segs: {len(unresolved)}")
json.dump(unresolved, open(os.path.join(HERE, f"segs_unresolved{SUF}.json"), "w"), ensure_ascii=False, indent=1)
for u in unresolved[:15]: print(" ", u["key"], u["seg"], "|", u["char"], "|", u["text"][:100])
