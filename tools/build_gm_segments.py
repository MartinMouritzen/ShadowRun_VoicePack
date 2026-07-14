#!/usr/bin/env python3
"""Build app/data/gm_segments.json: for every character line containing {{GM}} narration,
the ordered list of narration segment texts (to be voiced by the NARRATOR, separately from
the character's speech). $(s.name) resolves statically to the speaking character's name."""
import json, re, os

ROOT = os.path.join(os.path.dirname(__file__), "..")
c = json.load(open(os.path.join(ROOT, "app/data/characters.json")))

out = {}
for ch in c["characters"]:
    for l in ch["lines"]:
        segs = re.findall(r'\{\{GM\}\}([\s\S]*?)(?:\{\{/GM\}\}|$)', l["t"])
        if not segs: continue
        clean = []
        for s in segs:
            s = s.replace("$(s.name)", ch["name"])
            s = re.sub(r'\{\{/?[A-Za-z]*\}\}', '', s)
            s = re.sub(r'\s+', ' ', s).strip()
            if s: clean.append(s)
        if clean:
            out[f'{l["c"]}_{l["n"]}'] = clean

json.dump(out, open(os.path.join(ROOT, "app/data/gm_segments.json"), "w"), ensure_ascii=False, indent=1)
leftover = sum(1 for v in out.values() for s in v if "$(" in s)
print(f"gm_segments: {len(out)} lines, {sum(len(v) for v in out.values())} segments, unresolved vars: {leftover}")
