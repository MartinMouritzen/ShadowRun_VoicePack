#!/usr/bin/env python3
"""Fail closed when extracted dialogue ownership no longer matches reviewed attribution data.

Usage: audit_attribution.py [dms|dragonfall|hk]

This checks the generated characters file, not merely the correction recipes: every node has one
owner, GM-speaker nodes are narrator-owned, every remaining unattributed node is an explicit
skip/review, and the final destination of every ordered reattribution rule owns its node. Running
the rules in order matters because a broad historical correction can be refined by a later rule.
"""
import json
import os
import sys

import line_moves


GAME = sys.argv[1] if len(sys.argv) > 1 else "hk"
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game {GAME!r}")

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def classified_unattributed(rule, node):
    if not rule:
        return False
    target = (rule.get("nodes") or {}).get(str(node))
    return bool(rule.get("skip") or rule.get("review") or target in ("skip", "review"))


def main():
    data_dir = os.path.join(ROOT, "app", "data", GAME)
    chars = load(os.path.join(data_dir, "characters.json"))
    if not chars:
        sys.exit(f"ERROR: missing {data_dir}/characters.json")
    # The generated merge map is the live canonical identity graph. It includes both source-file
    # merge rules and merges performed through the Voice Lab.
    merges = load(os.path.join(data_dir, "merges.json"), {}) or {}
    rules = (load(os.path.join(HERE, "reattributions.json"), {}) or {}).get(GAME) or []
    suffix = "" if GAME == "dms" else f"_{GAME}"
    hand = load(os.path.join(HERE, f"unattributed_hand_attribution{suffix}.json"), {}) or {}

    owners = {}
    character_y6 = []
    buckets = [(c["id"], c.get("lines") or []) for c in chars.get("characters") or []]
    buckets += [("narrator", (chars.get("narrator") or {}).get("lines") or []),
                ("unattributed", (chars.get("unattributed") or {}).get("lines") or [])]
    for owner, lines in buckets:
        for line in lines:
            key = (line.get("c"), line.get("n"))
            owners.setdefault(key, []).append(owner)
            # HK's DTO enum was verified against its shipped data during the attribution audit.
            # Older games have existing y=6 routing that has not been migrated and must not be
            # silently reinterpreted by an HK-specific safety change.
            if GAME == "hk" and owner not in ("narrator", "unattributed") and line.get("y") == 6:
                character_y6.append((owner, key))

    errors = []
    duplicate = [(key, found) for key, found in owners.items() if len(found) != 1]
    if duplicate:
        errors.extend(f"duplicate node {key}: {found}" for key, found in duplicate)
    if character_y6:
        errors.extend(f"GM-speaker node {key} remains under {owner}" for owner, key in character_y6)

    unclassified = []
    for line in (chars.get("unattributed") or {}).get("lines") or []:
        rule = (hand.get("convos") or {}).get(line.get("c"))
        if not classified_unattributed(rule, line.get("n")):
            unclassified.append((line.get("c"), line.get("n"), line.get("cn")))
    errors.extend(f"unclassified unattributed node {key[:2]} ({key[2]})" for key in unclassified)

    # Later rules deliberately refine some older broad corrections. Model their final destination
    # in rule order, then inspect the generated file once rather than demanding every intermediate
    # owner still exist.
    expected = {}
    for rule in rules:
        try:
            target = line_moves.resolve_merge_target(rule["to"], merges)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        for node in rule.get("nodes") or []:
            expected[(rule["convo"], node)] = target
    wrong_rules = []
    for key, target in expected.items():
        found = owners.get(key) or []
        if found != [target]:
            wrong_rules.append((key, target, found))
    errors.extend(f"reviewed node {key} expected {target}, found {found}"
                  for key, target, found in wrong_rules)

    if errors:
        for error in errors[:100]:
            print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(f"FAILED attribution audit: {len(errors)} error(s)")
    gm_summary = ", 0 character-owned GM-speaker nodes" if GAME == "hk" else ""
    print(f"{GAME}: attribution audit passed — {len(owners)} uniquely owned nodes, "
          f"{len(expected)} reviewed corrections, "
          f"{len((chars.get('unattributed') or {}).get('lines') or [])} explicit skips/reviews"
          f"{gm_summary}")


if __name__ == "__main__":
    main()
