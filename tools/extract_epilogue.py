#!/usr/bin/env python3
"""Extract the end-of-campaign epilogue text and MERGE it into app/data/<game>/barks.json as a
Narrator entry with kind "epilogue".

The epilogue is the screen the game shows after the final scene ("The Emerald City Ripper killings
are sensationalized for several weeks..."). It lives in ContentPacks/<pack>/data/misc/epilogue*.bytes
and, unlike everything else the extractors read, that file is NOT protobuf -- it is the raw UTF-8
text, paragraphs separated by blank lines. No other extractor looks in data/misc/, which is why
this text was never in the lab and the ending played silently.

DMS ships ONE ending, in a file named exactly `epilogue.bytes`. Dragonfall and Hong Kong branch:
each ending is its own `epilogue_<state>.bytes` (Dragonfall 9 -- lab intact/destroyed x
Feuerschwinge killed/released/left behind/APEX, plus early exit and "the horrors"; Hong Kong 12 --
9 in HongKong plus 3 coda returns). Matching the bare filename therefore found nothing at all in
either game, so both campaigns' endings would have played silent exactly the way DMS's did. Every
variant is extracted: the player reaches only one, but which one is not knowable here.

Each paragraph becomes its own segment, so the narrator gets a beat between them instead of
reading four news items as one breathless block. The plugin plays them in order from one key.

KEY: the plugin hashes the text off the live EpilogueScreen label, so the key must match what is
on screen. Two keys are emitted for the same clips:
    bark_<md5(text.strip())>        exact, what the label should contain verbatim
    bark_<md5(whitespace-collapsed)> fallback, in case the UI layer re-wraps or re-spaces it
That costs nothing (both point at the same audio) and means a stray space cannot silence an
ending the player only reaches once.

Usage: extract_epilogue.py <ContentPacks_dir> <game:dms|dragonfall|hk> <pack1[,pack2,...]>
Always additive: existing bark entries (hand attribution, picks, takes) are never touched."""
import glob, hashlib, json, os, re, sys

SR, GAME, PACKS = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
OUT = os.path.join(os.path.dirname(__file__), "..", "app", "data", GAME, "barks.json")

def md5_16(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]

def collapse(s):
    return re.sub(r"\s+", " ", s).strip()

def main():
    found = []
    seen = set()
    for p in PACKS:
        for path in sorted(glob.glob(os.path.join(SR, p, "data", "misc", "epilogue*.bytes"))):
            raw = open(path, "rb").read().decode("utf-8", "replace")
            text = raw.strip()
            if len(text) < 40:
                continue
            # Branching endings share whole paragraphs, but each FILE is one screen, so identical
            # full texts (not paragraphs) are the only real duplicates and they collide on key.
            if text in seen:
                continue
            seen.add(text)
            # paragraphs: blank-line separated, whitespace tidied inside each
            paras = [collapse(x) for x in re.split(r"\n\s*\n", text) if collapse(x)]
            found.append((p, os.path.basename(path), text, paras))

    if not found:
        print(f"no data/misc/epilogue*.bytes in {', '.join(PACKS)} — nothing to do")
        return 0

    data = json.load(open(OUT)) if os.path.exists(OUT) else {}
    added = 0
    for pack, fname, text, paras in found:
        entry = {
            "text": text,
            "kind": "epilogue",
            "speaker": "Narrator (GM)",
            "charId": "narrator",
            "pack": pack,
            "variant": os.path.splitext(fname)[0],
            "segments": paras,
        }
        for key in ("bark_" + md5_16(text), "bark_" + md5_16(collapse(text))):
            if key in data:
                # keep whatever the lab already knows (picks/attribution), just refresh the text
                data[key].update({k: v for k, v in entry.items() if k not in ("charId",)})
            else:
                data[key] = dict(entry)
                added += 1
        print(f"[{GAME}] {pack}/{fname}: {len(paras)} paragraph(s), {len(text)} chars")
        for i, s in enumerate(paras):
            print(f"    {i}: {s[:88]}{'...' if len(s) > 88 else ''}")

    json.dump(data, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"[{GAME}] barks.json: {added} new key(s), {len(data)} total")
    return 0

if __name__ == "__main__":
    sys.exit(main())
