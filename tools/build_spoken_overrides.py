#!/usr/bin/env python3
"""Build app/data/<game>/spoken_overrides.json: per-line SPOKEN text for lines containing $()
variables (incl. the $+() and $(L.*) variants). Screen text stays untouched; audio uses the
override. Rules live in spoken_rules.py (shared with build_line_segments.py); lines they can't
fully clean are listed for hand-rewriting in the per-game HAND file (always wins over rules).

Usage: build_spoken_overrides.py [dms|dragonfall|hk]   (default dms)
Hand files: tools/spoken_hand_rewrites.json (dms, legacy name) /
            tools/spoken_hand_rewrites_<game>.json (dragonfall, hk)
Unresolved: tools/spoken_unresolved.json (dms) / tools/spoken_unresolved_<game>.json"""
import json, re, sys, os
from spoken_rules import mechanical, has_var, they_disagreement, nuyen
import re as _re

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    print(f"ERROR: unknown game '{GAME}'", file=sys.stderr); sys.exit(1)

ROOT = os.path.join(os.path.dirname(__file__), "..")
HERE = os.path.dirname(__file__)
SUF = "" if GAME == "dms" else f"_{GAME}"
c = json.load(open(os.path.join(ROOT, f"app/data/{GAME}/characters.json")))

HAND = {}
handfile = os.path.join(HERE, f"spoken_hand_rewrites{SUF}.json")
if os.path.exists(handfile):
    HAND = json.load(open(handfile))

# Lines a terminal only DISPLAYS, written by a person: the spoken text is the body alone, with the
# >>>>>[...]<<<<< markers, the ">>From:" header block and the "- Handle <10:55:01/...>" signature
# taken off (docs/SCREEN_SPEAKERS.md). Without this the brackets and the timestamps are read out.
#
# This wins over the HAND file, which it has to: 129 of Dragonfall's Computer lines have a hand
# rewrite and they bake in exactly what is being removed ("Mettbach, Gunari If you value new
# hardware coming into the Kreuzbasar..."). Where the stripped body still holds an unresolved $()
# the hand rewrite is kept and the line is reported, so a rewrite is never lost to a regression.
SCREEN = {}
screenfile = os.path.join(HERE, f"screen_splits_{GAME}.json")
if os.path.exists(screenfile):
    SCREEN = json.load(open(screenfile)).get("spoken") or {}
screen_kept_hand = []

def strip_gm(t):
    return re.sub(r'\{\{GM\}\}.*?(\{\{/GM\}\}|$)', ' ', t, flags=re.S)

overrides = {}
unresolved = []
def process(cid, cname, lines, is_narrator=False):
    for l in lines:
        # Angle-bracket speech needs an override for the same reason a variable does: what is
        # on screen is not what should be spoken, and without an override an unsegmented line
        # falls through to the raw text and reaches the TTS with the brackets still on it.
        # A yen sign needs an override for the same reason: left alone the line has no override at
        # all, the lab falls through to the raw text, and the TTS reads the glyph as "yen".
        hv = (has_var(l['t']) or _re.search(r'[<>]', l['t'] or '') is not None
              or '¥' in (l['t'] or ''))
        key = f"{l['c']}_{l['n']}"
        if key in SCREEN:
            s = mechanical(re.sub(r'\{\{/?[A-Za-z]*\}\}', '', strip_gm(SCREEN[key]))).strip()
            if s and '$(' not in s and not they_disagreement(s, SCREEN[key]):
                overrides[key] = {"char": cname, "original": l['t'], "spoken": s,
                                  "source": "screen-speaker"}
                continue
            if key in HAND:
                screen_kept_hand.append({"key": key, "char": cname, "body": SCREEN[key][:160]})
            else:
                unresolved.append({"key": key, "char": cname, "text": l['t']})
                continue
        if not hv and (is_narrator or '{{' not in l['t']):
            continue
        if key in HAND:
            # nuyen(): a hand rewrite is used verbatim and never sees mechanical(), so the ones
            # that were typed with the game's yen sign still carried it into the audio.
            overrides[key] = {"char": cname, "original": l['t'], "spoken": nuyen(HAND[key]),
                              "source": "hand"}
            continue
        if not hv:
            continue  # GM-span-only lines are handled at generation time, no override needed
        s = l['t'] if is_narrator else strip_gm(l['t'])
        s = mechanical(re.sub(r'\{\{/?[A-Za-z]*\}\}', '', s)).strip()
        # they_disagreement: $(l.he) becomes "they", and the singular verb the writers put after it
        # has to become plural or the line is spoken as "they's right" / "Does they have". The rules
        # cover the verbs actually present in the corpus; anything else is surfaced, not guessed at.
        if '$(' in s or not s or they_disagreement(s, l['t']):
            # {{GM}}-containing char lines are segmented: their fixes live in the per-game
            # hand-SEGMENTS file and are reported by build_line_segments.py — don't double-report.
            if is_narrator or '{{GM}}' not in l['t']:
                unresolved.append({"key": key, "char": cname, "text": l['t']})
        else:
            overrides[key] = {"char": cname, "original": l['t'], "spoken": s, "source": "rules"}

for ch in c["characters"]:
    process(ch["id"], ch["name"], ch["lines"])
if "narrator" in c:
    process("narrator", "Narrator", c["narrator"]["lines"], is_narrator=True)

json.dump(overrides, open(os.path.join(ROOT, f"app/data/{GAME}/spoken_overrides.json"), "w"),
          ensure_ascii=False, indent=1)
print(f"[{GAME}] overrides: {len(overrides)} ({sum(1 for v in overrides.values() if v['source']=='hand')} hand"
      + (f", {sum(1 for v in overrides.values() if v['source']=='screen-speaker')} screen-speaker" if SCREEN else "")
      + ")")
if screen_kept_hand:
    print(f"[{GAME}] {len(screen_kept_hand)} screen-speaker line(s) still hold an unresolved $() "
          f"after stripping, so their hand rewrite was kept — these still say the sender's name:")
    for e in screen_kept_hand[:20]:
        print("  !", e["key"], "|", e["char"], "|", e["body"][:90].replace("\n", " | "))
print(f"[{GAME}] unresolved (need hand rewrite): {len(unresolved)}")
json.dump(unresolved, open(os.path.join(HERE, f"spoken_unresolved{SUF}.json"), "w"),
          ensure_ascii=False, indent=1)
