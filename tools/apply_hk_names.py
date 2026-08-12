#!/usr/bin/env python3
"""Resolve HK conversation NPC names stored as $(story.*)/$(scene.*) template variables.

Hong Kong names many NPCs through story/scene string variables (e.g.
"$(story.MC_Hub-charName_Qiu)"); the extractor captured the raw variable string as the character
name, so the lab showed ugly unresolved names. The display name is set at runtime, but the
variable-name suffix is the character identity. tools/hk_name_resolution.json is the curated
variable -> clean-name map (34 entries).

This applies that map to app/data/hk/characters.json (a POST-extraction step, like
apply_reattributions.py): rename each $() character to its clean name, re-key its id to
name_<norm(clean)>, and migrate its char_notes entry. If a resolved name matches an EXISTING
non-variable character (a split, e.g. Hwang Jae-Min), the two are MERGED.

It also cleans barks.json SPEAKER fields, which it used to skip: a bark's speaker comes from the
scene actor's display name, so the same variables land there, and 21 Hong Kong barks were still
attributed to "$(scene.Convention_ConGoer3Name)". A speaker that is a token cannot be cast - it has
no bark_picks entry and no matching character - so those barks would have fallen through to the
narrator's voice.

Idempotent: characters and speakers whose name is no longer $()-shaped are skipped.
Usage: apply_hk_names.py
"""
import json, os, re, sys, unicodedata

ROOT = os.path.join(os.path.dirname(__file__), "..")
CH = os.path.join(ROOT, "app", "data", "hk", "characters.json")
NOTES = os.path.join(ROOT, "app", "data", "hk", "char_notes.json")
MAP = json.load(open(os.path.join(os.path.dirname(__file__), "hk_name_resolution.json")))
MAP = {k: v for k, v in MAP.items() if not k.startswith("_")}

def norm(t):
    t = unicodedata.normalize('NFKD', t or '')
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', t.lower())

ch = json.load(open(CH))
notes = json.load(open(NOTES)) if os.path.exists(NOTES) else {}
by_id = {c["id"]: c for c in ch["characters"]}

renamed = merged = 0
keep = []
for c in ch["characters"]:
    name = c["name"]
    if "$(" not in name:
        keep.append(c); continue
    clean = MAP.get(name)
    if not clean:
        keep.append(c); continue          # unmapped $() char: leave as-is (shouldn't happen)
    new_id = "name_" + norm(clean)
    target = by_id.get(new_id)
    if target is not None and target is not c:
        # MERGE into the existing resolved character
        target["lines"].extend(c["lines"])
        notes.pop(c["id"], None)           # drop the variable char's note; target keeps its own
        merged += 1
        continue                            # do not keep c
    # plain rename + re-key
    old_id = c["id"]
    c["name"] = clean
    c["id"] = new_id
    if old_id in notes and new_id not in notes:
        notes[new_id] = notes.pop(old_id)
    by_id[new_id] = c
    renamed += 1
    keep.append(c)

ch["characters"] = keep
json.dump(ch, open(CH, "w"), ensure_ascii=False, indent=1)
json.dump(notes, open(NOTES, "w"), ensure_ascii=False, indent=1)
print(f"HK names resolved: {renamed} renamed, {merged} merged into existing characters")

# Bark speakers. Barks are keyed by their TEXT, so unlike characters there is no id to re-key and
# nothing to merge - only the speaker string changes, which is what bark_picks.json is keyed on.
BARKS = os.path.join(ROOT, "app", "data", "hk", "barks.json")
if os.path.exists(BARKS):
    barks = json.load(open(BARKS))
    fixed, unmapped = 0, {}
    for k, b in barks.items():
        sp = b.get("speaker") or ""
        if "$(" not in sp:
            continue
        clean = MAP.get(sp) or MAP.get(sp.strip())
        if not clean:
            unmapped[sp] = unmapped.get(sp, 0) + 1
            continue
        b["speaker"] = clean
        fixed += 1
    if fixed:
        json.dump(barks, open(BARKS, "w"), ensure_ascii=False, indent=1)
    print(f"HK bark speakers resolved: {fixed}")
    for sp, n in sorted(unmapped.items(), key=lambda kv: -kv[1]):
        # Not silent: an unmapped variable is a speaker nobody can cast, and the only fix is a new
        # entry in hk_name_resolution.json. The variable-name suffix is the identity, and the story
        # variable's DEFAULT value in the scene blobs is usually the intended display name.
        print(f"  UNMAPPED speaker ({n} bark(s)): {sp} — add it to hk_name_resolution.json",
              file=sys.stderr)
