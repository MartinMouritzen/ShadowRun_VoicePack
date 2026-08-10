#!/usr/bin/env python3
"""Work out who wrote each line a terminal displays, and write the plan to
tools/screen_splits_<game>.json for apply_screen_splits.py.

    Usage: build_screen_splits.py [dms|dragonfall|hk] [--report]

`Computer`, `Admin Terminal`, `Message File` and their kin are surfaces, not characters. Most of
what they show was written by somebody. screen_text.py parses the structure; this script turns that
into moves, and leans on the per-game hand file for everything the parser is not entitled to decide.

Hand file: tools/screen_speakers_<game>.json

    conversations : {convo_id: {"cn": name, "default": "machine"|"<person>"}}
        A whole surface at once. A sewer pump console is machine top to bottom; a lab-notes terminal
        is one technician's journal top to bottom. Saying so once beats teaching the parser a
        regex per phrasing, and a regex that gets it backwards leaves a person in the robot voice.
    nodes         : {"<convo>_<n>": "machine"|"<person>"}   exceptions to the above
    people        : {name: {id, name, kind: bbs|new|existing, gender, note}}
    aliases       : {typo: canonical}      "Malestrom" is Maelstrom with a slip of the finger
    keep          : [name, ...]            handles that really are the machine, or are deliberately
                                           anonymous ("WITHHELD"), and stay with the container
    transcripts   : {"<convo>_<n>": {label: person}}   GUEST is Herr Schmidt in one thread and
                                           Herr Fuchs in the next; only a reader can tell

Nothing is invented: a speaker the hand file does not place is reported and left where it is.
"""
import json, os, re, sys
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen_text as st

GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
REPORT = "--report" in sys.argv
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CH_PATH = os.path.join(ROOT, "app", "data", GAME, "characters.json")
HAND_PATH = os.path.join(HERE, f"screen_speakers_{GAME}.json")
OUT_PATH = os.path.join(HERE, f"screen_splits_{GAME}.json")

chars = json.load(open(CH_PATH))
cast = chars["characters"]
by_id = {c["id"]: c for c in cast}
by_name = {c["name"]: c for c in cast}

hand = json.load(open(HAND_PATH)) if os.path.exists(HAND_PATH) else {}
# The plan from the last run, used only to pull already-moved lines back into the parse so a re-run
# reproduces itself instead of quietly emitting an empty plan.
PREVIOUS = (json.load(open(OUT_PATH)).get("moves") or []) if os.path.exists(OUT_PATH) else []
CONVS = hand.get("conversations") or {}
NODES = hand.get("nodes") or {}
PEOPLE = hand.get("people") or {}
ALIASES = hand.get("aliases") or {}
KEEP = set(hand.get("keep") or [])
TRANSCRIPTS = hand.get("transcripts") or {}
CONTAINERS = hand.get("containers") or []

MACHINE = "machine"


def canonical(who):
    return ALIASES.get(who, who)


def person(who):
    """The cast entry a screen speaker resolves to: (id, name, kind), or None when unplaced."""
    who = canonical(who)
    if who in KEEP:
        return None
    p = PEOPLE.get(who)
    if not p:
        return None
    return p["id"], p.get("name") or who, p.get("kind") or "new"


def main():
    moves = defaultdict(lambda: {"nodes": [], "kind": None})
    inline = {}
    spoken = {}
    unplaced = Counter()
    unknown = []
    stats = Counter()

    for container in CONTAINERS:
        c = by_id.get(container)
        if not c:
            print(f"  WARN: container {container} not in the cast", file=sys.stderr)
            continue
        byconv = defaultdict(list)
        for l in c["lines"]:
            byconv[l["c"]].append(l)

        # Re-running after apply_screen_splits.py must reproduce the SAME plan, not an empty one:
        # the lines have left the container by then, and an empty plan would quietly take
        # spoken_overrides' source of truth with it. It matters for the parse itself too — a
        # Shadowland post can span two nodes, and a pool with holes cannot see the second half.
        #
        # The previous plan names exactly which nodes left, so they are pulled back precisely.
        # Reassembling by CHARACTER instead would drag in a split-out person's own dialogue:
        # Paul Amsel has 354 lines of it and shares some of these conversations.
        want = {(m["convo"], n) for m in PREVIOUS if m["from"] == container for n in m["nodes"]}
        if want:
            for other in cast:
                if other["id"] == container:
                    continue
                for l in other["lines"]:
                    if (l["c"], l["n"]) in want:
                        byconv[l["c"]].append(l)

        for conv, ls in byconv.items():
            ls.sort(key=lambda l: l["n"])
            parsed = st.parse_conversation([(l["n"], l["t"]) for l in ls])
            cdefault = (CONVS.get(conv) or {}).get("default")

            for l in ls:
                key = f"{conv}_{l['n']}"
                entry = parsed[l["n"]]
                kind, who = entry["kind"], entry.get("who")

                override = NODES.get(key, None)
                if override is None and kind == st.UNKNOWN:
                    override = cdefault
                if override == MACHINE:
                    stats["machine"] += 1
                    continue
                if override:
                    who, kind = override, kind if kind != st.UNKNOWN else "hand"

                if kind == st.MACHINE:
                    stats["machine"] += 1
                    continue

                if kind == st.TRANSCRIPT_KIND or entry.get("multi"):
                    plan = split_node(container, conv, l, entry, unplaced)
                    if plan:
                        inline[key] = plan
                        # The node's own spoken text, so a build that does NOT segment it still
                        # says the right words rather than reading the markers out.
                        spoken[key] = "\n\n".join(p["text"] for p in plan)
                        stats["inline"] += 1
                    else:
                        unknown.append({"key": key, "cn": l["cn"], "why": "multi-speaker, unplaced",
                                        "text": l["t"][:160]})
                    continue

                if not who:
                    unknown.append({"key": key, "cn": l["cn"], "why": f"{kind}, no speaker",
                                    "text": l["t"][:160]})
                    stats["unknown"] += 1
                    continue

                resolved = person(who)
                if not resolved:
                    if canonical(who) not in KEEP:
                        unplaced[canonical(who)] += 1
                        unknown.append({"key": key, "cn": l["cn"], "why": f"unplaced speaker {who!r}",
                                        "text": l["t"][:160]})
                    else:
                        # Staying with the terminal is not a reason to read the furniture out:
                        # "System Error :: Thread Closed" was being spoken as
                        # "- System Daemon 03:28:19/11-17-54".
                        spoken[key] = st.spoken_body(l["t"], kind)
                    stats["kept"] += 1
                    continue

                pid, pname, pkind = resolved
                m = moves[(container, conv, pid)]
                m["nodes"].append(l["n"])
                m["from"], m["to"], m["convo"], m["cn"] = container, pid, conv, l["cn"]
                m["to_name"], m["kind"] = pname, pkind
                # The words this person actually says, with the terminal's furniture taken off.
                # Carried in the plan rather than re-derived, so build_spoken_overrides.py speaks
                # exactly what the split was decided on: one source of truth, and a diffable one.
                spoken[key] = st.spoken_body(l["t"], kind if kind in (st.BBS, st.MAIL) else st.BBS)
                stats["moved"] += 1

    out = {
        "_comment": ("Generated by build_screen_splits.py from characters.json + "
                     f"screen_speakers_{GAME}.json. Do not hand-edit: edit the hand file and "
                     "re-run. Applied by apply_screen_splits.py."),
        "game": GAME,
        "moves": sorted(
            ({"from": m["from"], "to": m["to"], "to_name": m["to_name"], "kind": m["kind"],
              "convo": m["convo"], "cn": m["cn"], "nodes": sorted(m["nodes"])}
             for m in moves.values()),
            key=lambda m: (m["to"], m["convo"])),
        "inline": inline,
        "spoken": spoken,
        "unplaced": dict(unplaced.most_common()),
        "unknown": unknown,
    }
    json.dump(out, open(OUT_PATH, "w"), ensure_ascii=False, indent=1)

    people = {m["to"] for m in out["moves"]}
    print(f"[{GAME}] {stats['moved']} lines move to {len(people)} people "
          f"in {len(out['moves'])} rules; {stats['inline']} nodes split in place; "
          f"{stats['machine']} stay machine; {stats['kept']} kept with the container")
    if unplaced:
        print(f"[{GAME}] {len(unplaced)} speakers not in the hand file "
              f"({sum(unplaced.values())} lines): "
              + ", ".join(f"{k} x{v}" for k, v in unplaced.most_common(12)))
    if stats["unknown"]:
        print(f"[{GAME}] {stats['unknown']} nodes the parser could not place — see 'unknown' in "
              f"{os.path.basename(OUT_PATH)}")
    if REPORT:
        for u in unknown[:60]:
            print("  ?", u["key"], "|", u["cn"], "|", u["why"], "|",
                  u["text"][:90].replace("\n", " | "))


def split_node(container, conv, line, entry, unplaced):
    """[{who, id, name, text}] for a node with several speakers in it, or None."""
    key = f"{conv}_{line['n']}"
    text = line["t"]
    parts = []

    labels = TRANSCRIPTS.get(key)
    if entry["kind"] == st.TRANSCRIPT_KIND or labels:
        if not labels:
            return None
        for m in re.finditer(r'^(?P<who>[A-Z][A-Z0-9_]{1,20}):[ \t]*(?P<t>.*)$', text, re.M):
            who = labels.get(m.group("who"))
            if not who:
                unplaced[m.group("who")] += 1
                return None
            r = person(who)
            if not r:
                unplaced[who] += 1
                return None
            body = m.group("t").strip()
            if not body:
                continue
            if parts and parts[-1]["id"] == r[0]:
                parts[-1]["text"] += " " + body
            else:
                parts.append({"who": who, "id": r[0], "name": r[1], "text": body})
        return parts or None

    # several BBS posts in one node
    pos = 0
    while True:
        o = st.OPEN.search(text, pos)
        if not o:
            break
        close = st.CLOSE.search(text, o.end())
        if not close:
            return None
        body = text[o.end():close.start()]
        who, rest = st._sig_head(text[close.end():])
        pos = len(text) - len(rest)
        if not who:
            continue
        r = person(who)
        if not r:
            unplaced[canonical(who)] += 1
            return None
        parts.append({"who": who, "id": r[0], "name": r[1],
                      "text": st.spoken_body(body, st.BBS)})
    return parts or None


main()
