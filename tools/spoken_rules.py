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
    return s

def has_var(t):
    return re.search(r'\$\+?\(', t) is not None

# player-address variables safe to DROP when used as a vocative ("..., $(l.name)?" etc.)
_VOC = r'l\.name|l\.Name|l\.firstname|l\.lastname|l\.sir|l\.Sir|l\.honorific|l\.freund|s\.name'

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
    s = re.sub(r'[Tt]here \$\(l\.he\) is', 'there they are', s)
    s = re.sub(r'\$\(l\.he\) is', 'they are', s)
    s = re.sub(r'\$\(l\.he\)', 'they', s)
    s = re.sub(r'\$\(l\.him\)', 'them', s)
    s = re.sub(r'\$\(l\.(his|hisher)\)', 'their', s)
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
