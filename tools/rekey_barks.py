#!/usr/bin/env python3
"""Carry a bark's takes from one key to another, on disk and in the take store.

A bark key IS the md5 of the words, so a bark can only be re-keyed when the words did not change -
which is exactly the case extract_loadscreens.py produces when it retires a story-variable token
placeholder: the recording is fine, it was simply filed under the token instead of under the text
it actually says. Re-keying keeps that audio instead of re-buying it.

Reads the map the extractors write (tools/gen/bark_rekey.json), or an explicit old:new pair. For
every mapping it moves takes.json["_barks"][<old>] and every <old>~gN segment to the new key,
renames the mp3s under app/audio/<game>/_barks/takes/ so the filename still states its key, and
rewrites the 'file'/'selected' paths to match.

The map's "dropped" list is the other half: keys whose bark entry was retired because it was never
narration at all (a story-variable token, a popup's title bar). Their take records are DELETED here,
because a take under a key no bark owns is invisible in the lab and yet still ships a clip. The mp3s
are left on disk - app/audio is git-ignored scratch, and keeping them costs nothing if a retirement
later turns out to be wrong.

bark_segments.json is NOT touched: the lab derives it from barks.json and rewrites the whole file,
so a beat list for a key that no longer exists disappears on the next lab state fetch.

Usage: rekey_barks.py <game> [--from-map] [old:new ...] [--dry]

Idempotent: a mapping whose old key is already gone is reported and skipped, so re-running after a
partial run is safe. Refuses to overwrite a new key that already has takes, because that would mean
two different recordings claim the same words and picking one silently is not this script's call.
"""
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
args = sys.argv[1:]
GAME = next((a for a in args if not a.startswith("-") and ":" not in a), None)
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(__doc__)
DRY = "--dry" in args
pairs = [tuple(a.split(":", 1)) for a in args if ":" in a and not a.startswith("-")]

DATA = os.path.join(ROOT, "app", "data", GAME)
AUDIO = os.path.join(ROOT, "app", "audio", GAME, "_barks", "takes")
TAKES = os.path.join(DATA, "takes.json")
MAP = os.path.join(HERE, "gen", "bark_rekey.json")

drops = []
if "--from-map" in args or not pairs:
    if not os.path.exists(MAP):
        sys.exit(f"no rekey map at {MAP} — run extract_loadscreens.py / extract_extras_game.py first")
    doc = json.load(open(MAP)).get(GAME) or {}
    pairs += sorted((doc.get("rekey") or {}).items())
    drops = list(doc.get("dropped") or [])
if not pairs and not drops:
    sys.exit("nothing to do: no mappings")

takes = json.load(open(TAKES))
bucket = takes.setdefault("_barks", {})
moved = files = purged = 0

for old, new in pairs:
    keys = [k for k in bucket if k == old or k.startswith(old + "~")]
    if not keys:
        print(f"skip {old} -> {new}: no takes under the old key (already re-keyed?)")
        continue
    clash = [k for k in bucket if k == new or k.startswith(new + "~")]
    if clash:
        print(f"REFUSING {old} -> {new}: the new key already has takes ({len(clash)}). "
              f"Two recordings claim the same words; resolve by hand.", file=sys.stderr)
        continue
    for k in sorted(keys):
        nk = new + k[len(old):]                      # carries the ~gN suffix
        rec = bucket[k]
        for t in rec.get("takes") or []:
            src_rel = t.get("file") or ""
            dst_rel = src_rel.replace(k, nk, 1) if k in src_rel else src_rel
            src, dst = os.path.join(ROOT, "app", "audio", GAME, src_rel), \
                       os.path.join(ROOT, "app", "audio", GAME, dst_rel)
            if src_rel != dst_rel and os.path.exists(src):
                print(f"  mv {os.path.basename(src)} -> {os.path.basename(dst)}")
                if not DRY: shutil.move(src, dst)
                files += 1
            elif src_rel != dst_rel:
                print(f"  WARN: missing audio {src_rel} (record moves anyway)", file=sys.stderr)
            t["file"] = dst_rel
        if rec.get("selected"):
            rec["selected"] = rec["selected"].replace(k, nk, 1)
        bucket[nk] = rec
        del bucket[k]
        moved += 1
        print(f"  {k} -> {nk}")

for k in drops:
    dead = sorted(x for x in bucket if x == k or x.startswith(k + "~"))
    if not dead:
        continue
    for x in dead:
        print(f"  purge {x} (bark retired; audio left on disk)")
        if not DRY: del bucket[x]
        purged += 1

if DRY:
    print(f"[dry] would move {moved} take records / {files} files, purge {purged}")
else:
    tmp = TAKES + ".tmp"
    json.dump(takes, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, TAKES)                            # atomic: the lab may be reading this
    print(f"moved {moved} take records / {files} files, purged {purged} "
          f"-> {os.path.relpath(TAKES, ROOT)}")
