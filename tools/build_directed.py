#!/usr/bin/env python3
"""Build app/data/<game>/directed.json: default performance direction (ElevenLabs v3 audio tags)
for speech segments, mined from the narration around them and from the shape of the speech itself.

Layering: user edit (text_edits.json) > directed.json > raw segment text.
Costs zero credits to author; tags add a few chars at generation time.

WHY PER-BEAT: eleven_v3 applies a [tag] to the words after it, until the next tag. A single
blanket tag at the head of a line ("[sad] Oh God. What have I done?") sets one register and lets
the rest of the line flatten out. Direction lands far better when every emotional micro-beat gets
its own tag, and best of all on TRANSITION tags ([dread rising], [steadying]) rather than repeated
state tags. So this splits a line into beats and tags a beat whenever the register CHANGES.

Density is deliberately capped: too many tags make v3 over-act, and it will occasionally read a
tag aloud. A segment is only directed at all when there is a confident signal, so flat expository
lines are left clean rather than sprayed with guesses.

Hand-authored entries in directed_hand.json always win and are copied through untouched.

Usage: python3 tools/build_directed.py [dms|dragonfall|hk]   (default dms)
"""
import json, os, re, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
HERE = os.path.dirname(__file__)
GAME = next((a for a in sys.argv[1:] if not a.startswith("-")), "dms")

# ---------------------------------------------------------------- registers
# A small closed set of performance registers. Narration cues and the speech's own shape both
# resolve to one of these, so a change between beats can be detected and named.
REGISTER_TAG = {
    "hushed":      "[whispering]",
    "fearful":     "[frightened]",
    "sad":         "[sad]",
    "angry":       "[angry]",
    "cold":        "[flat, cold]",
    "amused":      "[amused]",
    "warm":        "[warm]",
    "nervous":     "[nervous]",
    "weary":       "[weary]",
    "urgent":      "[urgent]",
    "pleading":    "[pleading]",
    "resolute":    "[steady, resolute]",
    "incredulous": "[incredulous]",
    "excited":     "[excited]",
}

# Transition tags are the highest-value direction: they tell the model to MOVE, not just to sit in
# a state. Keyed by the register being entered; a few from->to pairs get something more specific.
TRANSITION_IN = {
    "fearful":     "[dread rising]",
    "sad":         "[voice falling]",
    "angry":       "[hardening]",
    "cold":        "[going flat]",
    "amused":      "[dry]",
    "warm":        "[softening]",
    "nervous":     "[faltering]",
    "weary":       "[deflating]",
    "urgent":      "[urgency rising]",
    "pleading":    "[voice cracking, pleading]",
    "resolute":    "[steadying]",
    "incredulous": "[rising, incredulous]",
    "excited":     "[brightening]",
    "hushed":      "[dropping to a whisper]",
}
TRANSITION_PAIR = {
    ("fearful", "resolute"):  "[steadying]",
    ("sad", "resolute"):      "[gathering herself]",
    ("angry", "cold"):        "[cooling to ice]",
    ("cold", "angry"):        "[snapping]",
    ("sad", "amused"):        "[a bitter laugh]",
    ("sad", "excited"):       "[brightening]",
    ("amused", "cold"):       "[smile gone]",
    ("amused", "angry"):      "[smile gone, hardening]",
    ("warm", "sad"):          "[faltering]",
    ("urgent", "hushed"):     "[dropping to a whisper]",
    ("nervous", "resolute"):  "[steadying]",
}

# ------------------------------------------------------- narration -> register
# Cues read from the {{GM}} narration that wraps a line; it frequently describes the delivery
# outright ("her voice is low, shaky"). Ordered: first match wins, so put specific before generic.
NARRATION_CUES = [
    (r"whisper|voice is (low|quiet|barely|hushed)|under (his|her|their) breath", "hushed"),
    (r"shout|yell|scream|bellow|roar|barks? (out|back)",                          "angry"),
    (r"snarl|growl|through (gritted|clenched) teeth|face contorts|spits|glares",  "angry"),
    (r"furious|rage|seething|temper|slams",                                       "angry"),
    (r"sob|cries|weep|tears|voice cracks|grief|remorse|mourn|choked",             "sad"),
    (r"laugh|chuckle|giggle|cackle|snicker|grins|smirks|winks|wry|amused",        "amused"),
    (r"sigh|wearily|tiredly|exhausted|rubs (his|her|their) (eyes|face)|slumps",   "weary"),
    (r"nervous|anxious|jumpy|fidget|stammer|swallows hard|shifts uncomfortably",  "nervous"),
    (r"trembl|shaking voice|voice is .{0,20}(shak|unsteady)|quaver",              "fearful"),
    (r"pale|horror|terrified|terror|fear in|flinch|recoils|frightened",           "fearful"),
    (r"coldly|icy|flat, cold|expressionless|deadpan|without emotion|clinical",    "cold"),
    (r"excited|beaming|lights up|enthusias|eager|delighted",                      "excited"),
    (r"steels|composes|straightens|squares (his|her|their) shoulders|firmly|resolve", "resolute"),
    (r"pleads|begging|begs|desperate|imploring",                                  "pleading"),
    (r"gently|softly|kindly|warmly|smiles (sadly|softly)?|reassuring",            "warm"),
    (r"urgent|hurried|quickly|hisses|snaps",                                      "urgent"),
]

# --------------------------------------------------- speech shape -> register
# Signals read from a beat's own words. These are what lift coverage: most lines have no narration
# describing delivery, but their punctuation and openers still carry the performance.
SPEECH_CUES = [
    (r"^(please|i'?m begging|don'?t|no,? please)\b",            "pleading"),
    (r"^(listen|look|wait|stop|hey|get (down|out|back))\b",     "urgent"),
    (r"^(what|you'?re joking|you can'?t be|seriously|are you)\b.*\?$", "incredulous"),
    (r"\b(kill|dead|die|blood|corpse|body)\b.*[!?]$",           "urgent"),
    (r"^(i'?m sorry|forgive me|i didn'?t mean)\b",              "sad"),
    (r"^(thank you|thanks|i appreciate)\b",                     "warm"),
    (r"^(fuck|shit|damn|hell)\b",                               "angry"),
]

PIVOTS = re.compile(r"^(but|and yet|still|except|however|then again|only|though)\b", re.I)

# Sentence/beat boundary: a terminator (keeping "..." intact) plus any closing quote, then space.
BEAT_SPLIT = re.compile(r"(\.\.\.|[.!?]+)([\"'”’\)\]]*)(\s+)")
TAG_RE = re.compile(r"\[[^\]]*\]\s*")


def split_beats(text):
    """Spans covering `text` end to end, broken at sentence boundaries. Lossless: the spans
    concatenate back to exactly the input."""
    spans, start = [], 0
    for m in BEAT_SPLIT.finditer(text):
        end = m.end()
        spans.append((start, end))
        start = end
    if start < len(text):
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def narration_register(text):
    low = text.lower()
    for pat, reg in NARRATION_CUES:
        if re.search(pat, low):
            return reg
    return None


def speech_register(beat, prev):
    """Register for one beat from its own shape, or None if it says nothing confident."""
    b = beat.strip()
    if not b:
        return None
    low = b.lower()
    core = TAG_RE.sub("", low).strip(" \"'“”")
    for pat, reg in SPEECH_CUES:
        if re.search(pat, core):
            return reg
    # A pivot conjunction marks a turn in the argument; pair it with the punctuation to decide
    # which way the register moves.
    pivot = bool(PIVOTS.match(core))
    # Trailing off is the one punctuation signal strong enough to direct on its own: "..." is
    # hesitation, and v3 reads it as such only when told the voice is faltering.
    if b.endswith("...") and len(core.split()) <= 12:
        return "nervous" if prev not in ("nervous", "hushed") else None
    # "!" and "?" already carry their own delivery. Tag them only as a MID-LINE turn, where the
    # rise is the thing worth directing, never as a line's opening register.
    if b.endswith("!") and prev:
        return "angry" if prev in ("angry", "urgent") else "urgent"
    if b.endswith("?") and (pivot or prev in ("angry", "urgent")):
        return "incredulous"
    if pivot:
        return "resolute" if prev in ("sad", "weary", "nervous", "fearful") else None
    # Deliberately no short-fragment rule: a clipped one-word sentence already reads as clipped
    # from its punctuation, and inferring an emotion (cold? angry? stunned?) from length alone was
    # wrong far more often than right.
    return None


def tag_for(prev, cur, first):
    if first:
        return REGISTER_TAG.get(cur)
    return (TRANSITION_PAIR.get((prev, cur))
            or TRANSITION_IN.get(cur)
            or REGISTER_TAG.get(cur))


def direct(text, before_reg, after_reg):
    """Insert per-beat tags. Returns the directed text, or None if there is nothing confident
    to say about this line."""
    if "[" in text or "]" in text:
        return None                      # would make tag parsing ambiguous; leave it clean
    spans = split_beats(text)
    nbeats = len(spans)
    cap = 1 if nbeats == 1 else min(4, 1 + nbeats // 2)

    # Opening register: what the narration before the line says, else the first beat's own shape.
    opening = before_reg or speech_register(text[spans[0][0]:spans[0][1]], None)
    if not opening and not after_reg:
        return None                      # nothing to direct with

    out, used, prev, placed = [], 0, None, False
    for i, (a, b) in enumerate(spans):
        beat = text[a:b]
        if i == 0:
            reg = opening
        else:
            reg = speech_register(beat, prev)
            # The narration AFTER the line describes how it ended: land that on the final beat.
            if i == nbeats - 1 and after_reg and after_reg != prev:
                reg = after_reg
        if reg and reg != prev and used < cap:
            tag = tag_for(prev, reg, not placed)
            # A tag with no words after it directs nothing and is one more chance for v3 to read
            # it aloud, so never tag a beat that has no spoken content left.
            if tag and re.search(r"[^\W\d_]", beat):
                lead = len(beat) - len(beat.lstrip())
                out.append(beat[:lead] + tag + " " + beat[lead:])
                used += 1
                prev = reg
                placed = True
                continue
        if reg:
            prev = reg
        out.append(beat)

    if used == 0:
        return None
    directed = "".join(out)
    # Safety: tags must only ADD to the line, never alter a word of it.
    assert TAG_RE.sub("", directed) == text, f"tag insertion changed the text: {text!r}"
    return directed


def main():
    seg_path = os.path.join(ROOT, f"app/data/{GAME}/line_segments.json")
    if not os.path.exists(seg_path):
        print(f"no line_segments.json for '{GAME}' at {seg_path}")
        return 2
    segs = json.load(open(seg_path))

    # Every segment key this game actually has, so hand entries authored for a different game
    # (directed_hand.json is shared but its keys are per-game) never leak into this one's file.
    valid = set()
    for key, parts in segs.items():
        nchar = sum(1 for s in parts if s["who"] == "char")
        ci = 0
        for s in parts:
            if s["who"] == "char":
                valid.add(key if nchar == 1 else f"{key}~c{ci}")
                ci += 1

    hand_path = os.path.join(HERE, "directed_hand.json")
    ALL_HAND = json.load(open(hand_path)) if os.path.exists(hand_path) else {}
    HAND = {k: v for k, v in ALL_HAND.items() if k in valid}
    foreign = len(ALL_HAND) - len(HAND)

    directed = dict(HAND)                # hand entries win, untouched
    auto = 0
    beats_tagged = 0
    for key, parts in segs.items():
        nchar = sum(1 for s in parts if s["who"] == "char")
        ci = 0
        for i, s in enumerate(parts):
            if s["who"] != "char":
                continue
            skey = key if nchar == 1 else f"{key}~c{ci}"
            ci += 1
            if skey in directed:
                continue
            before = parts[i - 1]["t"] if i > 0 and parts[i - 1]["who"] == "gm" else None
            after = parts[i + 1]["t"] if i + 1 < len(parts) and parts[i + 1]["who"] == "gm" else None
            d = direct(s["t"],
                       narration_register(before) if before else None,
                       narration_register(after) if after else None)
            if d:
                directed[skey] = d
                auto += 1
                beats_tagged += len(TAG_RE.findall(d))

    out_path = os.path.join(ROOT, f"app/data/{GAME}/directed.json")
    json.dump(directed, open(out_path, "w"), ensure_ascii=False, indent=1)
    avg = (beats_tagged / auto) if auto else 0
    print(f"directed[{GAME}]: {len(directed)} segments "
          f"({auto} auto-mined, {avg:.1f} tags/line avg, {len(HAND)} hand"
          + (f", {foreign} hand entries skipped as not this game's" if foreign else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
