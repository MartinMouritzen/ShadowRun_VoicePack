#!/usr/bin/env python3
"""Build app/data/dms/spoken_overrides.json: per-line SPOKEN text for lines containing $() variables.
Screen text stays untouched; audio uses the override. Policy (Martin 2026-07-13): rewrite lines to
read naturally without the variable (drop vocatives, neutral relationship words); NEVER 'chummer'.
Character overrides also drop {{GM}} narration spans (those belong to the narrator's voice).
Mechanical rules here; lines they can't fully clean are listed for hand-rewriting in HAND (below,
keyed by convoId_nodeIndex), which always wins over rules."""
import json, re, sys, os

ROOT = os.path.join(os.path.dirname(__file__), "..")
c = json.load(open(os.path.join(ROOT, "app/data/dms/characters.json")))

HAND = {}
handfile = os.path.join(os.path.dirname(__file__), "spoken_hand_rewrites.json")
if os.path.exists(handfile):
    HAND = json.load(open(handfile))

def strip_gm(t):
    return re.sub(r'\{\{GM\}\}.*?(\{\{/GM\}\}|$)', ' ', t, flags=re.S)

def mechanical(t):
    s = t
    # vocative drops: ", $(l.name)?" -> "?"  (also sir/firstname/man-as-name etc.)
    s = re.sub(r',\s*\$\((l\.name|l\.Name|l\.firstname|l\.sir|l\.Sir|s\.name)\)\s*([.!?,])', r'\2', s)
    s = re.sub(r'^\s*\$\((l\.name|l\.Name|l\.firstname)\)\s*[,-]\s*', '', s)
    # greetings: "Welcome $(scene.BroSis)!" -> "Welcome, friend!"
    s = re.sub(r'\$\(scene\.BroSis\)', 'friend', s)
    # gendered address words: 'man' works cross-gender in street slang
    s = re.sub(r',\s*\$\(l\.man\)\s*([.!?,])', r', man\1', s)
    s = re.sub(r'\$\(l\.man\)', 'man', s)
    # "quite a $(l.guy)" -> "really something"
    s = re.sub(r'quite (a|the) \$\(l\.guy\)', 'really something', s)
    # pronouns about the player: neutral 'they' forms (verb-agreement fixups below)
    s = re.sub(r'[Tt]here \$\(l\.he\) is', 'there they are', s)
    s = re.sub(r'\$\(l\.he\) is', 'they are', s)
    s = re.sub(r'\$\(l\.he\)', 'they', s)
    s = re.sub(r'\$\(l\.him\)', 'them', s)
    s = re.sub(r'\$\(l\.(his|hisher)\)', 'their', s)
    # tidy whitespace/punctuation artifacts
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s+([.!?,])', r'\1', s)
    return s

overrides = {}
unresolved = []
def process(cid, cname, lines, is_narrator=False):
    for l in lines:
        if '$(' not in l['t'] and (is_narrator or '{{' not in l['t']):
            continue
        key = f"{l['c']}_{l['n']}"
        if key in HAND:
            overrides[key] = {"char": cname, "original": l['t'], "spoken": HAND[key], "source": "hand"}
            continue
        if '$(' not in l['t']:
            continue  # GM-span-only lines are handled at generation time, no override needed
        s = l['t'] if is_narrator else strip_gm(l['t'])
        s = mechanical(re.sub(r'\{\{/?[A-Za-z]*\}\}', '', s)).strip()
        if '$(' in s or not s:
            unresolved.append({"key": key, "char": cname, "text": l['t']})
        else:
            overrides[key] = {"char": cname, "original": l['t'], "spoken": s, "source": "rules"}

for ch in c["characters"]:
    process(ch["id"], ch["name"], ch["lines"])
process("narrator", "Narrator", c["narrator"]["lines"], is_narrator=True)

json.dump(overrides, open(os.path.join(ROOT, "app/data/dms/spoken_overrides.json"), "w"),
          ensure_ascii=False, indent=1)
print(f"overrides: {len(overrides)} ({sum(1 for v in overrides.values() if v['source']=='hand')} hand)")
print(f"unresolved (need hand rewrite): {len(unresolved)}")
json.dump(unresolved, open(os.path.join(os.path.dirname(__file__), "spoken_unresolved.json"), "w"),
          ensure_ascii=False, indent=1)
