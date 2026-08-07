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
    return re.search(r'\$\+?\(', t) is not None

# player-address variables safe to DROP when used as a vocative ("..., $(l.name)?" etc.)
_VOC = r'l\.name|l\.Name|l\.firstname|l\.lastname|l\.sir|l\.Sir|l\.honorific|l\.freund|s\.name'

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


def _cap_substituted(s):
    """Replace the pronoun tokens with their words, capitalizing any that opens a sentence.
    Only tokens THIS module inserted are considered, so the writers' own casing is untouched."""
    rx = '|'.join(_SUBBED)
    s = re.sub(r'(^|[.!?]\s+|["“]\s*)(' + rx + r')',
               lambda m: m.group(1) + _SUBBED[m.group(2)].capitalize(), s)
    for tok, word in _SUBBED.items():
        s = s.replace(tok, word)
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

def mechanical(t):
    s = normalize(t)
    # canonical story strings (HK) — substitute BEFORE vocative logic so they read in character
    s = re.sub(r'\$\(story\.Global_Gobbet_Nickname\)', 'Seattle', s)
    s = re.sub(r'\$\(story\.Global_HK_Hub_SafeBoatName\)', 'Bolthole', s, flags=re.I)
    # vocative drops: ", $(l.name)?" -> "?"  (also sir/first/lastname/honorific/freund etc.)
    s = re.sub(r',\s*\$\((%s)\)\s*([.!?,])' % _VOC, r'\2', s)
    s = re.sub(r'^\s*\$\((l\.name|l\.Name|l\.firstname|l\.honorific)\)\s*[,-]\s*', '', s)
    # greetings: "Welcome $(scene.BroSis)!" -> "Welcome, friend!"
    s = re.sub(r'\$\(scene\.BroSis\)', 'friend', s)
    # gendered address words: 'man' works cross-gender in street slang
    s = re.sub(r',\s*\$\(l\.man\)\s*([.!?,])', r', man\1', s)
    s = re.sub(r'\$\(l\.man\)', 'man', s)
    # "quite a $(l.guy)" -> "really something"
    s = re.sub(r'quite (a|the) \$\(l\.guy\)', 'really something', s)
    # pronouns about the player: neutral 'they' forms
    s = re.sub(r'([Tt])here \$\(l\.he\) is', r'\1here they are', s)
    s = _they(s)
    s = re.sub(r'\$\(l\.him\)', _TOK_THEM, s)
    s = re.sub(r'\$\(l\.(his|hisher)\)', _TOK_THEIR, s)
    s = _cap_substituted(s)
    # tidy whitespace/punctuation artifacts
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s+([.!?,])', r'\1', s)
    return s

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
