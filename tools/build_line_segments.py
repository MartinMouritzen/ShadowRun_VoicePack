#!/usr/bin/env python3
"""Build app/data/line_segments.json: for every character line containing {{GM}} narration,
the ORDERED list of playback segments: [{who: 'gm'|'char', t: spoken_text}, ...].
Preserves interleaving (narration - speech - narration - speech). gm segments are voiced by the
narrator ($(s.name) resolves to the speaking character's name); char segments get the same
variable-rewrite treatment as spoken_overrides (HAND single-speech rewrites win; per-segment
hand fixes live in spoken_hand_segments.json)."""
import json, re, os

ROOT = os.path.join(os.path.dirname(__file__), "..")
HERE = os.path.dirname(__file__)
c = json.load(open(os.path.join(ROOT, "app/data/characters.json")))
HAND = json.load(open(os.path.join(HERE, "spoken_hand_rewrites.json"))) if os.path.exists(os.path.join(HERE, "spoken_hand_rewrites.json")) else {}
HAND_SEG = json.load(open(os.path.join(HERE, "spoken_hand_segments.json"))) if os.path.exists(os.path.join(HERE, "spoken_hand_segments.json")) else {}

def mechanical(t):  # keep in sync with build_spoken_overrides.py
    s = t
    s = re.sub(r',\s*\$\((l\.name|l\.Name|l\.firstname|l\.sir|l\.Sir|s\.name)\)\s*([.!?,])', r'\2', s)
    s = re.sub(r'^\s*\$\((l\.name|l\.Name|l\.firstname)\)\s*[,-]\s*', '', s)
    s = re.sub(r'\$\(scene\.BroSis\)', 'friend', s)
    s = re.sub(r',\s*\$\(l\.man\)\s*([.!?,])', r', man\1', s)
    s = re.sub(r'\$\(l\.man\)', 'man', s)
    s = re.sub(r'quite (a|the) \$\(l\.guy\)', 'really something', s)
    s = re.sub(r'[Tt]here \$\(l\.he\) is', 'there they are', s)
    s = re.sub(r'\$\(l\.he\) is', 'they are', s)
    s = re.sub(r'\$\(l\.he\)', 'they', s)
    s = re.sub(r'\$\(l\.him\)', 'them', s)
    s = re.sub(r'\$\(l\.(his|hisher)\)', 'their', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s+([.!?,])', r'\1', s)
    return s

def clean(t):
    return re.sub(r'\s+', ' ', re.sub(r'\{\{/?[A-Za-z]*\}\}', '', t)).strip()

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
    for l in ch["lines"]:
        key = f'{l["c"]}_{l["n"]}'
        if l.get("y") == 6 and "{{GM}}" not in l["t"]:
            # GM_Speaker_Voice without markers: the whole node is narration -> narrator voices it
            result[key] = [{"who": "gm", "t": clean(l["t"].replace("$(s.name)", ch["name"]))}]
            continue
        if "{{GM}}" not in l["t"]: continue
        segs = raw_segments(l["t"])
        nchar = sum(1 for w, _ in segs if w == "char")
        out = []; ci = 0
        for who, raw in segs:
            if who == "gm":
                out.append({"who": "gm", "t": clean(raw.replace("$(s.name)", ch["name"]))})
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

json.dump(result, open(os.path.join(ROOT, "app/data/line_segments.json"), "w"), ensure_ascii=False, indent=1)
multi = sum(1 for v in result.values() if sum(1 for s in v if s["who"] == "char") >= 2)
print(f"segmented lines: {len(result)} ({multi} with interleaved speech); unresolved segs: {len(unresolved)}")
for u in unresolved: print(" ", u["key"], u["seg"], "|", u["char"], "|", u["text"][:120])
