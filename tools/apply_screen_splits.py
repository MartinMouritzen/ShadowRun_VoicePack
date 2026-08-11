#!/usr/bin/env python3
"""Apply tools/screen_splits_<game>.json to app/data/<game>/: move the lines a terminal was only
DISPLAYING to the people who actually wrote them.

    Usage: apply_screen_splits.py [dms|dragonfall|hk] [--dry-run]

Run after merge_characters.py and before build_spoken_overrides.py — see docs/SCREEN_SPEAKERS.md
for the full order. Idempotent: a line is moved only if it is still under the container, so a
re-run after a fresh extract is a no-op for anything already in place.

Lines, take records and take audio all move together (line_moves.py), because takes.json is
bucketed by character id and build_voicepack.py looks a line up under its OWNING character.

The keeper take is CLEARED on every moved line. A take record stores no text and no hash of it, so
a clip generated before the split — Microsoft David reading a Shadowland post complete with its
timestamp — is indistinguishable from a good one, and build_voicepack.py would happily ship it
under the new character's name. The clips stay in the take list to audition; they just stop being
the keeper until the line is regenerated in its real voice.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import line_moves

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
DRY = "--dry-run" in sys.argv
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
DATA = os.path.join(ROOT, "app", "data", GAME)
AUDIO = os.path.join(ROOT, "app", "audio", GAME)
PLAN_PATH = os.path.join(HERE, f"screen_splits_{GAME}.json")
HAND_PATH = os.path.join(HERE, f"screen_speakers_{GAME}.json")

if not os.path.exists(PLAN_PATH):
    sys.exit(f"ERROR: no plan at {PLAN_PATH} — run build_screen_splits.py {GAME} first")

plan = json.load(open(PLAN_PATH))
hand = json.load(open(HAND_PATH)) if os.path.exists(HAND_PATH) else {}
PEOPLE = hand.get("people") or {}
by_person = {p["id"]: p for p in PEOPLE.values()}

chars = json.load(open(os.path.join(DATA, "characters.json")))
by_id = {c["id"]: c for c in chars["characters"]}
takes_path = os.path.join(DATA, "takes.json")
takes = json.load(open(takes_path)) if os.path.exists(takes_path) else {}

created, moved_total, take_groups, skipped = [], 0, 0, 0

# ---- reconcile with what a previous run actually did -------------------------------------------
# Editing the hand file can UNCLAIM a line — reclassifying a payment ledger the mail-run had
# swallowed back to machine, say. Moves alone are one-way, so without this the line would sit under
# the wrong character forever and no amount of re-running would fix it. Only lines this tool moved
# are ever moved back; a split-out person's own dialogue is not ours to touch.
APPLIED_PATH = os.path.join(HERE, f"screen_splits_{GAME}.applied.json")
applied = json.load(open(APPLIED_PATH)) if os.path.exists(APPLIED_PATH) else {"moves": []}
claimed = {(m["convo"], n): m["to"] for m in plan["moves"] for n in m["nodes"]}
returned = 0
for old in applied.get("moves", []):
    stale = [n for n in old["nodes"] if claimed.get((old["convo"], n)) != old["to"]]
    if not stale or old["to"] not in by_id:
        continue
    back = claimed.get((old["convo"], stale[0])) or old["from"]
    for n in stale:
        dest = claimed.get((old["convo"], n)) or old["from"]
        if dest not in by_id:
            continue
        moved = line_moves.move_lines(by_id[old["to"]], by_id[dest], old["convo"], {n})
        if moved:
            # Going home to the container means going back to the voice and the words the clip was
            # made with, so the keeper survives. Being reassigned to somebody ELSE does not.
            line_moves.move_takes(takes, AUDIO, old["to"], dest, old["convo"], {n},
                                  clear_selected=(dest != old["from"]))
            returned += moved
if returned:
    print(f"[{GAME}] returned {returned} line(s) the plan no longer claims")

for rule in plan["moves"]:
    src, dst, convo, nodes = rule["from"], rule["to"], rule["convo"], set(rule["nodes"])
    if src not in by_id:
        sys.exit(f"ERROR: container '{src}' is not in the cast")

    if dst == "narrator":
        # The narrator is not a cast entry in these packs, it is a top-level bucket. Lines routed
        # here are prose the writers never tagged, so nothing downstream would ever have found it.
        n = line_moves.move_lines(by_id[src], chars["narrator"], convo, nodes)
        moved_total += n
        if n:
            take_groups += len(line_moves.move_takes(takes, AUDIO, src, "narrator", convo, nodes,
                                                     clear_selected=True))
        else:
            skipped += 1
        continue

    p = by_person.get(dst, {})
    target, is_new = line_moves.ensure_character(
        chars, by_id, dst, rule["to_name"],
        # A BBS handle is not part of the cast for casting purposes: the lab must not count its
        # voice as taken, or the main crew gets cast out of a pool this pass already ate.
        screenSpeaker=("bbs" if rule.get("kind") == "bbs" else None),
        gender=p.get("gender"))
    if is_new:
        created.append(f"{dst} ({rule['to_name']!r})")

    n = line_moves.move_lines(by_id[src], target, convo, nodes)
    moved_total += n
    if n:
        take_groups += len(line_moves.move_takes(takes, AUDIO, src, dst, convo, nodes,
                                                 clear_selected=True))
    else:
        skipped += 1

# Casting comes from the same hand file, so a person and their voice are described in one place.
# setdefault, never overwrite: anything recast in the lab has to survive a re-run.
#
# Only people who OWN lines get a pick. Someone who appears solely inside a shared node (Big Pharma
# and Mr. Mayhem only ever post in a thread that shares its node with Clockwork) has no cast entry,
# and a pick keyed to a character that does not exist would be deleted by apply_reattributions.py's
# orphan sweep on its next run. Their voice rides on the seg_overrides entry instead, exactly as a
# quote-split speaker's does.
owners = {m["to"] for m in plan["moves"]}
picks_path = os.path.join(DATA, "picks.json")
picks = json.load(open(picks_path)) if os.path.exists(picks_path) else {}
cast_now = []
for name, p in PEOPLE.items():
    if not p.get("voiceId") or p["id"] in picks or p["id"] not in owners:
        continue
    picks[p["id"]] = {"voiceId": p["voiceId"], "voiceName": p.get("voiceName")}
    cast_now.append(f"{p['name']} -> {p.get('voiceName')}")

# Equipment, not people. build_directed.py refuses to put a mood on a character carrying this flag
# (see MACHINES in that file); the lab and the packs are otherwise indifferent to it. Kept in the
# hand file rather than derived from the name at read time, because a keyword test catches people
# speaking through a fixture as readily as the fixture itself.
machines = set(hand.get("machines") or [])
flagged = 0
for c in chars["characters"]:
    want = c["id"] in machines and not c.get("screenSpeaker")
    if want and not c.get("machine"):
        c["machine"] = True
        flagged += 1
    elif c.get("machine") and not want:
        c.pop("machine")
        flagged += 1
if flagged:
    print(f"[{GAME}] machine flag changed on {flagged} character(s); {len(machines)} are equipment")

print(f"[{GAME}] moved {moved_total} line(s) in {len(plan['moves']) - skipped} rule(s) "
      f"({skipped} already applied); carried {take_groups} take group(s)")
if created:
    print(f"[{GAME}] created {len(created)} character(s): " + ", ".join(sorted(created)))
if cast_now:
    print(f"[{GAME}] cast {len(cast_now)} new character(s)")
    for c in sorted(cast_now):
        print("   ", c)
print(f"[{GAME}] {len(plan['inline'])} node(s) are split in place — build_line_segments.py voices "
      f"those from the same plan")

if DRY:
    print("(--dry-run: nothing written)")
    sys.exit(0)

json.dump(chars, open(os.path.join(DATA, "characters.json"), "w"), ensure_ascii=False, indent=1)
json.dump(takes, open(takes_path, "w"), ensure_ascii=False, indent=1)
json.dump(picks, open(picks_path, "w"), ensure_ascii=False, indent=1)
# What was actually applied, so the next run can tell an unclaimed line from someone else's.
json.dump({"moves": plan["moves"]}, open(APPLIED_PATH, "w"), ensure_ascii=False, indent=1)
