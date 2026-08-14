"""Shared $()-variable spoken-rewrite rules for all three games (single source of truth for
build_spoken_overrides.py and build_line_segments.py — these used to carry drifting copies).

Policy (Martin 2026-07-13): screen text stays untouched; SPOKEN text must read naturally without
the variable. Drop vocatives, use neutral relationship words, NEVER 'chummer'. Lines the rules
can't fully clean are surfaced as unresolved for hand rewriting.

Fixed story-string substitutions (verified against HK story.story.bytes defaults 2026-07-17):
  $(story.Global_Gobbet_Nickname) -> "Seattle"   (Gobbet's default nickname for the PC; player-
                                                  changeable in one convo, but Seattle is canonical)
  $(story.Global_HK_Hub_SafeBoatName) -> "Bolthole" (the crew's boat; default name)
"""
import re

def normalize(t):
    """Fold the variable-syntax variants into the base form: $+() is the capitalized-substitution
    variant, $(L.*) is a case-variant of $(l.*) (both appear in HK/DF data)."""
    s = t.replace('$+(', '$(')
    s = re.sub(r'\$\(L\.', '$(l.', s)
    # Writers' typo: the parenthesis and the dollar are transposed, "($l.name)" for "$(l.name)".
    # has_var() does not match it, so the line was never even offered for rewriting and the raw
    # token went to TTS to be read aloud. Three Dragonfall lines (Glory's APEX confrontation).
    s = re.sub(r'\(\$([a-zA-Z])\.([^)]*)\)', r'$(\1.\2)', s)
    return s

def has_var(t):
    # \$\+?\( matched $( and $+( but NOT $++(, so every emphatic variable was invisible to the
    # detector that decides which lines need resolving - which is how 54 of them reached the TTS.
    return re.search(r'\$\+*\(', t) is not None

# player-address variables safe to DROP when used as a vocative ("..., $(l.name)?" etc.)
_VOC = r'l\.name|l\.Name|l\.firstname|l\.lastname|l\.sir|l\.Sir|l\.honorific|l\.freund|s\.name|l\.race|l\.metatype'

# ---------------------------------------------------------------- $(l.he) -> "they"
# The writers wrote every player pronoun as third-person SINGULAR, because at runtime the game
# substitutes "he" or "she". Rendering it as singular "they" leaves the verb behind it inflected
# for the wrong number, and the result is spoken aloud: "they's right", "they needs *what?*",
# "Does they have the stomach for this?", "they doesn't talk much". 66 lines across the three
# games, two of them already shipped in Dead Man's Switch.
#
# The pronoun is substituted as a TOKEN first so agreement is only ever repaired around the word
# this function inserted. The writers' own "they"/"is"/"has" elsewhere in the line is never
# touched -- rewriting those would be altering the game's dialogue, which this module must not do.
_TOK = "\x01THEY\x01"
_TOK_THEM, _TOK_THEIR = "\x01THEM\x01", "\x01THEIR\x01"
_SUBBED = {_TOK: "they", _TOK_THEM: "them", _TOK_THEIR: "their"}


def _shouting(s):
    """Is this line written in caps? APEX, the Strange Woman and the cyberzombie all shout whole
    lines, and v3 reads caps as volume."""
    letters = [ch for ch in s if ch.isalpha()]
    return len(letters) > 12 and sum(ch.isupper() for ch in letters) / len(letters) > 0.8


def _cap_substituted(s):
    """Replace the pronoun tokens with their words, capitalizing any that opens a sentence.
    Only tokens THIS module inserted are considered, so the writers' own casing is untouched.

    In a shouted line the inserted word is upper-cased to match: dropping a lower-case "them" into
    "I WILL NOT HARM $++(L.HIM)" tells v3 to stop shouting for one word in the middle of a threat."""
    shout = _shouting(s)
    rx = '|'.join(_SUBBED)
    s = re.sub(r'(^|[.!?]\s+|["“]\s*)(' + rx + r')',
               lambda m: m.group(1) + _SUBBED[m.group(2)].capitalize(), s)
    for tok, word in _SUBBED.items():
        s = s.replace(tok, word.upper() if shout else word)
    return s
_AUX_AFTER = {"is": "are", "was": "were", "has": "have", "does": "do",
              "isn't": "aren't", "wasn't": "weren't", "hasn't": "haven't", "doesn't": "don't"}
_AUX_BEFORE = {"is": "are", "was": "were", "has": "have", "does": "do"}
# Regular third-person-singular verbs observed directly after the pronoun. Deliberately a closed
# list, not a "strip a trailing s" heuristic: that would maul plural nouns and past tenses.
_V3SG = {"wants": "want", "needs": "need", "looks": "look", "means": "mean", "insists": "insist",
         "provokes": "provoke", "deserves": "deserve", "belongs": "belong", "wishes": "wish",
         "thinks": "think", "says": "say", "knows": "know", "gets": "get", "goes": "go",
         "takes": "take", "makes": "make", "seems": "seem", "comes": "come", "gives": "give",
         "tells": "tell", "keeps": "keep", "lets": "let", "leaves": "leave", "works": "work"}


def _they(s):
    if '$(l.he)' not in s:
        return s
    s = s.replace('$(l.he)', _TOK)
    # contraction on the pronoun itself: "$(l.he)'s right" -> "they're right"
    s = re.sub(_TOK + r"\s*['’]s\b", _TOK + " are", s)
    # auxiliary AFTER the pronoun
    s = re.sub(_TOK + r' (' + '|'.join(re.escape(k) for k in _AUX_AFTER) + r')\b',
               lambda m: _TOK + ' ' + _AUX_AFTER[m.group(1)], s)
    # auxiliary BEFORE the pronoun, incl. the contracted "What's $(l.he) doing?" form
    s = re.sub(r"(?<![-\w])(what|where|who|how|why|when)['’]s (?=" + _TOK + r')',
               lambda m: m.group(1) + ' are ', s, flags=re.I)
    # (?<![-\w]) so the stutter the writers spell as "D-does" is not treated as a bare "does"
    def _before(m):
        w = _AUX_BEFORE[m.group(1).lower()]
        return (w.capitalize() if m.group(1)[0].isupper() else w) + ' '
    s = re.sub(r'(?<![-\w])(' + '|'.join(_AUX_BEFORE) + r') (?=' + _TOK + r')',
               _before, s, flags=re.I)
    # regular third-person-singular verb after the pronoun
    s = re.sub(_TOK + r' (' + '|'.join(_V3SG) + r')\b',
               lambda m: _TOK + ' ' + _V3SG[m.group(1)], s)
    return s          # tokens are resolved (and capitalized) by _cap_substituted()


def they_disagreement(t, original=None):
    """Spoken text where the substituted 'they' is still followed by a singular verb the closed
    lists above did not cover. The builders surface these for hand rewriting rather than guessing
    at a verb this module does not know.

    `original` is the pre-substitution text. Without it this flags the writers' own grammatical
    prose too: Duncan's "whatever the fuck it is they do" is correct English and contains no
    variable at all. Only a line where $(l.he) was actually substituted can be wrong this way."""
    if original is not None and '$(l.he)' not in normalize(original):
        return False
    return re.search(r'\bthey (?:is|was|has|does|isn\'t|wasn\'t|hasn\'t|doesn\'t)\b'
                     r"|\bthey['’]s\b"
                     r'|\b(?:is|was|does|has) they\b', t, re.I) is not None

# Angle brackets are formatting, never speech. The game uses <...> for telepathy and spirit voices
# (the Heart of Feuerstelle speaks entirely in them) and >>...<< for screen text. The provider
# parses <...> as markup, strips it, and rejects what is left: "Input at position 0 has empty
# text" - which is how 24 of the Heart's lines failed. They must come off before anything is sent.
_ANGLE = re.compile(r"[<>]+")

def strip_angles(t):
    return re.sub(r"\s{2,}", " ", _ANGLE.sub(" ", t or "")).strip()


def mechanical(t):
    s = strip_angles(normalize(t))
    # The engine writes the same variables three ways: $(l.name), $+(l.name) and $++(L.NAME) -
    # the plus marks an emphatic substitution and the case follows the surrounding sentence. Every
    # rule below matches a bare lower-case $(var), so a shouted "$++(L.NAME)" slipped through all
    # of them untouched and was read out as "dollar plus plus paren L dot name" - 54 segments of
    # it, 40 already generated. Fold the prefix here and match the player variables case-insensitively.
    s = re.sub(r"\$\++\(", "$(", s)
    # canonical story strings (HK) — substitute BEFORE vocative logic so they read in character
    s = re.sub(r'\$\(story\.Global_Gobbet_Nickname\)', 'Seattle', s)
    s = re.sub(r'\$\(story\.Global_HK_Hub_SafeBoatName\)', 'Bolthole', s, flags=re.I)
    # vocative drops: ", $(l.name)?" -> "?"  (also sir/first/lastname/honorific/freund etc.)
    s = re.sub(r',\s*\$\((%s)\)\s*([.!?,])' % _VOC, r'\2', s, flags=re.I)
    # A line that OPENS by naming the player: "$(l.name). I didn't want to say this in front of the
    # others" — the full stop belongs in the class as much as the comma does.
    s = re.sub(r'^\s*\$\((l\.name|l\.firstname|l\.honorific)\)\s*[,.-]\s*', '', s, flags=re.I)
    # Letter salutations. Screen mail is written as a letter and opens on one, which no vocative
    # rule above reaches because it is a line of its own inside the body. "Dear," alone is not
    # English, so that one takes the neutral relationship word; the rest just lose the name.
    s = re.sub(r'^[ \t]*Dear[ \t,]*\$\((?:l\.name|l\.firstname)\)\s*,',
               'Dear friend,', s, flags=re.I | re.M)
    s = re.sub(r'^[ \t]*(Hi|Hello|Hey|Hoi|Yo|Greetings)[ \t,]*\$\((?:l\.name|l\.firstname)\)\s*[,.!]',
               r'\1,', s, flags=re.I | re.M)
    # greetings: "Welcome $(scene.BroSis)!" -> "Welcome, friend!"
    s = re.sub(r'\$\(scene\.BroSis\)', 'friend', s)
    # gendered address words: 'man' works cross-gender in street slang
    s = re.sub(r',\s*\$\(l\.man\)\s*([.!?,])', r', man\1', s, flags=re.I)
    s = re.sub(r'\$\(l\.man\)', 'man', s, flags=re.I)
    # "quite a $(l.guy)" -> "really something"
    s = re.sub(r'quite (a|the) \$\(l\.guy\)', 'really something', s)
    # pronouns about the player: neutral 'they' forms
    s = re.sub(r'([Tt])here \$\(l\.he\) is', r'\1here they are', s)
    s = _they(s)
    s = re.sub(r'\$\(l\.him\)', _TOK_THEM, s, flags=re.I)
    s = re.sub(r'\$\(l\.(his|hisher)\)', _TOK_THEIR, s, flags=re.I)
    s = _cap_substituted(s)
    s = nuyen(s)
    # tidy whitespace/punctuation artifacts
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s+([.!?,])', r'\1', s)
    return s

# ---------------------------------------------------------------- currency
# Shadowrun's money is the NUYEN, and the games write it with the yen sign - before the amount
# ("¥50,000") in Hong Kong's prose, after it ("22,500¥") in Dragonfall's terminal printouts. The
# glyph is a real currency symbol, so every TTS reads it as "yen": a different currency, in a
# setting that never uses the word. The amount has to be spoken the way the setting says it,
# which puts the unit AFTER the number in both writing orders: "50,000 nuyen".
_AMOUNT = r'\d[\d,]*(?:\.\d+)?'
# "about ¥950 million" must not become "950 nuyen million" - the scale word belongs to the number.
_SCALE = r'(?:\s+(?:hundred|thousand|million|billion|trillion))*'

def nuyen(t):
    """Rewrite yen-sign amounts as spoken nuyen. Idempotent: text with no ¥ comes back unchanged."""
    s = t or ""
    if '¥' not in s:
        return s
    # symbol first, over a literal amount or over a variable that will hold one
    # ("CURRENT FUNDS: ¥$(story.Global_AliceFunds)")
    s = re.sub(r'¥\s*(' + _AMOUNT + r'|\$\+*\([^)]*\))(' + _SCALE + r')', r'\1\2 nuyen', s)
    # symbol last, including the negative line items of a payout statement ("-1,500¥")
    s = re.sub(r'(' + _AMOUNT + r')\s*¥', r'\1 nuyen', s)
    return s.replace('¥', 'nuyen')          # anything left is a bare symbol


def resolve_speaker_vars(t, speaker_name, gender=None):
    """Resolve $(s.*) variables: they refer to the SPEAKING character, whose name/gender we know
    statically. Used for narration segments ('$(s.he) pulls a flask from $(s.hisher) jacket')."""
    s = normalize(t).replace('$(s.name)', speaker_name)
    he, him, his = ('he', 'him', 'his') if gender == 'male' else \
                   ('she', 'her', 'her') if gender == 'female' else ('they', 'them', 'their')
    s = re.sub(r'\$\(s\.(he|heshe)\)', he, s)
    s = re.sub(r'\$\(s\.him\)', him, s)
    s = re.sub(r'\$\(s\.(his|hisher)\)', his, s)
    return s

# ---------------------------------------------------------------- long-line beats
# A take you cannot audition is a take you cannot fix. A 600-character line is a 45-second clip:
# checking it means sitting through the whole thing, and changing one sentence means regenerating
# and re-listening to all of it. Splitting on the author's own paragraph breaks makes each beat
# separately auditionable, regeneratable and payable-for, and the pack stitches them back together
# so the game still hears one continuous line.
#
# NOTE: lab/spoken.py carries the same rule under bark_segments(), for the barks the lab produces
# itself. The two must stay in step; they are duplicated because this repo is standalone and must
# not import the private lab.
SEG_MAX = 400          # chars; above this a paragraph is broken further, at sentence ends
# Deliberately conservative: an ellipsis is NOT a sentence end, because this prose trails off
# constantly and cutting there strands a fragment starting mid-thought. The next sentence must
# also start like one (capital, digit, quote or bracket).
_SENTENCE_END = re.compile(r"""(?<!\.\.)(?<=[.!?])["'”’]?\s+(?=["“'(\[A-Z0-9])""")

def beats(text, maxlen=SEG_MAX):
    """The beats a line is generated in. One element means it stays whole."""
    out = []
    for para in re.split(r"\n\s*\n+", text or ""):
        para = re.sub(r"\s+", " ", para).strip()
        if not para:
            continue
        if len(para) <= maxlen:
            out.append(para)
            continue
        cur = ""
        for sentence in _SENTENCE_END.split(para):
            if cur and len(cur) + 1 + len(sentence) > maxlen:
                out.append(cur)
                cur = sentence
            else:
                cur = f"{cur} {sentence}".strip()
        if cur:
            out.append(cur)
    return out
