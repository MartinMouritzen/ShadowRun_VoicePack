#!/usr/bin/env python3
"""Template-variable variants: the words the game substitutes, voiced for real.

A Shadowrun line like "Greetings, young $(l.race)." is authored once and displayed five ways.
Until now the lab dodged those: spoken_overrides rewrote the sentence to avoid the word, so an ork
player heard a line that carefully never said "ork". This module enumerates the values a variable
can actually take, so the same line can be generated once per value and the plugin can play the one
that matches the playthrough.

Only CLOSED variables are expandable. $(l.name) is the player's typed name and $(scene.numUnread-
Messages) is a counter - those stay generic forever, and callers get an empty list for them.

The value sets are not guessed. Gender and metatype come from the game's own word lists; the scene
strings (badfantasy, CafeSpecial, str_RedOrGreen) are read out of the shipped scene blobs by
scan_scene_values(), because a "Set Variable (string)" action carries its literal inline.
"""
import glob, os, re

# ---------------------------------------------------------------- closed value sets
# Keyed by the lower-cased token inside $(...). Each entry maps a variant id -> the substituted
# word. The variant id is what ends up in the clip key, so it must be filename-safe and stable.
GENDER = {"m": "male", "f": "female"}
RACE = {"human": "human", "elf": "elf", "dwarf": "dwarf", "ork": "ork", "troll": "troll"}

# Per-token substitution by gender. $+(...) is the capitalised form (start of a sentence); the
# caller applies that, this table is lower-case.
GENDER_WORDS = {
    "l.he": {"m": "he", "f": "she"},
    "s.he": {"m": "he", "f": "she"},
    "l.him": {"m": "him", "f": "her"},
    "s.him": {"m": "him", "f": "her"},
    "l.his": {"m": "his", "f": "her"},
    "s.his": {"m": "his", "f": "her"},
    "l.hisher": {"m": "his", "f": "her"},
    "s.hisher": {"m": "his", "f": "her"},
    "l.himher": {"m": "him", "f": "her"},
    "l.man": {"m": "man", "f": "woman"},
    "l.guy": {"m": "guy", "f": "gal"},
    "l.sir": {"m": "sir", "f": "ma'am"},
    "l.honorific": {"m": "sir", "f": "ma'am"},
    # Kreuzbasar German: Monika and Dietrich call you friend in the gendered form.
    "l.freund": {"m": "Freund", "f": "Freundin"},
}
RACE_WORDS = {t: {k: v for k, v in RACE.items()} for t in ("l.race", "l.metatype")}

# Aljernon's fantasy-speak: one token that varies on BOTH race and gender at once, so its axis is
# the pair rather than either alone. Values read from the scene blobs; the mapping of pair -> word
# is his own invention, so it is listed rather than derived.
BADFANTASY = {
    "human.m": "sir", "human.f": "madam",
    "elf.m": "elfling", "elf.f": "she-elf",
    "dwarf.m": "dwarfling", "dwarf.f": "dwarfling",
    "ork.m": "ork-man", "ork.f": "she-ork",
    "troll.m": "he-troll", "troll.f": "she-troll",
}

VAR_RE = re.compile(r"\$(\+*)\(([^)]*)\)")
# Never expandable: a typed name, a running count, a date, a money total.
UNBOUNDED = re.compile(r"^(l\.(name|lastname|firstname)|story\.|scene\.(num|active|str_amount))", re.I)


def scan_scene_values(content_packs, token):
    """Every string literal assigned to a scene/story variable, read from the shipped blobs.

    A "Set Variable (string)" action stores the variable name followed by its literal, so the
    values are recoverable without running the game. Used for the scene strings whose sets are
    content, not engine constants (CafeSpecial's seven drinks change with mission progress).
    """
    # The token is lower-cased by callers, the blob spells it "CafeSpecial" - match either.
    name = token.split(".", 1)[-1]
    pat = re.compile(re.escape(name.encode()), re.I)
    def rv(b, i):
        v = s = 0
        while True:
            x = b[i]; i += 1; v |= (x & 0x7f) << s; s += 7
            if not x & 0x80:
                return v, i
    out = set()
    for f in glob.glob(os.path.join(content_packs, "**", "*.bytes"), recursive=True):
        b = open(f, "rb").read()
        for m in pat.finditer(b):
            i = m.end()
            if i >= len(b) or b[i] != 0x12:
                continue
            try:
                _, j = rv(b, i + 1)
                if j < len(b) and b[j] == 0x22:
                    n, k = rv(b, j + 1)
                    if 0 < n < 200:
                        out.add(b[k:k + n].decode("utf-8", "replace"))
            except IndexError:
                pass
    return sorted(out)


def axes(text, scene_sets=None):
    """The variant axes a text varies on: a subset of {'race', 'gender', 'scene:<tok>'}.

    Empty means one clip covers every playthrough. An unbounded variable also yields empty - the
    line still gets its single generic take, exactly as before.
    """
    scene_sets = scene_sets or {}
    found = set()
    for _, tok in VAR_RE.findall(text or ""):
        t = tok.lower()
        if UNBOUNDED.match(t):
            continue
        if t == "scene.badfantasy":
            found |= {"race", "gender"}          # one word, but it moves on both axes
        elif t in GENDER_WORDS:
            found.add("gender")
        elif t in RACE_WORDS:
            found.add("race")
        elif t in scene_sets:
            found.add("scene:" + t)
    return found


def combos(ax, scene_sets=None):
    """Every variant id for a set of axes, as an ordered list of (variant_id, bindings)."""
    scene_sets = scene_sets or {}
    out = [("", {})]
    for a in sorted(ax):
        if a == "race":
            vals = [(r, {"race": r}) for r in RACE]
        elif a == "gender":
            vals = [(g, {"gender": g}) for g in GENDER]
        else:
            tok = a.split(":", 1)[1]
            vals = [(slug(v), {a: v}) for v in scene_sets.get(tok, [])]
        if not vals:
            continue          # nothing known for this axis - one generic clip still covers it
        out = [((f"{i}.{j}" if i else j), {**b, **nb}) for i, b in out for j, nb in vals]
    return out


def slug(v):
    """A filename-safe, stable id for a free-form scene string."""
    s = re.sub(r"[^a-z0-9]+", "-", (v or "").lower()).strip("-")
    return s[:24] or "x"


def render(text, bindings, scene_sets=None):
    """`text` with every expandable variable substituted for this variant.

    Unbounded variables are left untouched - the existing rewrite layer (spoken_overrides /
    spoken_hand_rewrites) still owns those, and stripping them here would silently change words
    that were already reviewed and voiced.
    """
    def sub(m):
        caps, tok = m.group(1), m.group(2)
        t = tok.lower()
        word = None
        if t == "scene.badfantasy":
            key = f"{bindings.get('race','human')}.{bindings.get('gender','m')}"
            word = BADFANTASY.get(key)
        elif t in GENDER_WORDS:
            word = GENDER_WORDS[t].get(bindings.get("gender"))
        elif t in RACE_WORDS:
            word = RACE_WORDS[t].get(bindings.get("race"))
        else:
            for k, v in bindings.items():
                if k == "scene:" + t:
                    word = v
        if word is None:
            return m.group(0)
        return word[:1].upper() + word[1:] if caps else word
    return VAR_RE.sub(sub, text or "")
