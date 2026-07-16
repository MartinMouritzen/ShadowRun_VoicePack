#!/usr/bin/env python3
"""Build app/data/dms/directed.json: default performance direction (ElevenLabs v3 audio tags)
for speech segments, mined from the narration that surrounds them - the {{GM}} text often
literally describes the delivery ("her voice is low, shaky" -> [shaky]).
Layering: user edit (text_edits.json) > directed.json > raw segment text.
Costs zero credits to author; tags add a few chars at generation time."""
import json, re, os

ROOT = os.path.join(os.path.dirname(__file__), "..")
HERE = os.path.dirname(__file__)
segs = json.load(open(os.path.join(ROOT, "app/data/dms/line_segments.json")))

# conservative cue -> v3 tag mapping; only fires on explicit delivery descriptions
CUES = [
 (r'voice is (low|quiet|barely|a whisper)|whisper', "[whispers]"),
 (r'voice is .{0,20}(shak|trembl)|shaking voice|trembling', "[shaky]"),
 (r'(shouts|yells|screams|bellows|roars)', "[shouts]"),
 (r'(snarls|growls|through (gritted|clenched) teeth|face contorts|hideous snarl)', "[angry]"),
 (r'(sighs|wearily|tiredly)', "[sighs]"),
 (r'(laughs|chuckles|giggles|cackles)', "[laughs]"),
 (r'(sobs|cries|tears|weep|voice cracks|grief)', "[sad]"),
 (r'(nervous|anxious|jumpy|fidget|stammers|swallows hard)', "[nervous]"),
 (r'(grins|smirks|smiles slyly|winks)', "[mischievously]"),
 (r'(coldly|icy|flat, cold|expressionless)', "[cold]"),
 (r'(excited|beaming|lights up|enthusiasm)', "[excited]"),
 (r'(pale|horror|terrified|fear in)', "[fearful]"),
]

HAND = {}
handfile = os.path.join(HERE, "directed_hand.json")
if os.path.exists(handfile):
    HAND = json.load(open(handfile))

directed = dict(HAND)  # hand entries win
auto = 0
for key, parts in segs.items():
    nchar = sum(1 for s in parts if s["who"] == "char")
    gi = 0; ci = 0
    pending = None  # tag mined from the narration immediately before a speech segment
    for s in parts:
        if s["who"] == "gm":
            gi += 1
            low = s["t"].lower()
            pending = None
            for pat, tag in CUES:
                if re.search(pat, low):
                    pending = tag
                    break
        else:
            skey = key if nchar == 1 else f"{key}~c{ci}"
            ci += 1
            if pending and skey not in directed:
                directed[skey] = f"{pending} {s['t']}"
                auto += 1
            pending = None

json.dump(directed, open(os.path.join(ROOT, "app/data/dms/directed.json"), "w"), ensure_ascii=False, indent=1)
print(f"directed: {len(directed)} segments ({auto} auto-mined from narration cues, {len(HAND)} hand)")
