#!/usr/bin/env python3
"""Extract the game's built-in HELP SCREEN tutorials into app/data/<game>/tutorials.json.

These are not the scene popups. Two different systems show tutorial text:

  DisplayTextInPopup   a scene action, authored per map, already captured in barks.json
  ShowHelpScreenPopup  the engine's own help screen ("Spend your Karma", "Etiquette"...),
                       whose text lives in the UI string table inside resources.assets

Only the first was ever voiced, because barks.json is built from scene data and the help screen
is not in scene data at all. The plugin hooks it by hashing the displayed body text, exactly as it
does for inspect one-liners, so the key here is tut_<md5(text)[:16]>.

The UI string table is one flat, alphabetically sorted, NUL-separated blob holding every string in
the game - menu labels, item descriptions, error messages and tutorials together. There is no
marker saying which is which, so candidates are selected by shape (long second-person prose) and
then filtered by a HAND list, because the shape test cannot tell "Karma represents the experience
characters earn..." from "Are you sure you would like to rewind this save game...". A list can.

Usage: extract_tutorials.py <game> <resources.assets path> [--write]
"""
import hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = sys.argv[1] if len(sys.argv) > 1 else "dragonfall"
ASSETS = sys.argv[2] if len(sys.argv) > 2 else ""
WRITE = "--write" in sys.argv
OUT = os.path.join(HERE, "..", "app", "data", GAME, "tutorials.json")
HAND = os.path.join(HERE, f"tutorial_keep_{GAME}.json")

# Not tutorials, however much they look like prose: save/load confirmations, store and Workshop
# errors, crash text. They are transient UI chatter, and a voice reading "Are you sure?" aloud
# every time you rewind a save would be intolerable.
REJECT = re.compile(
    r"are you sure|would you like|autosave|checkpoint|steam|workshop|content pack|"
    r"try again later|unresponsive|failed to|could not|error|version of the game|"
    r"subscrib|purchase|download|servers|save game|overwrite|delete", re.I)


def strings_around(blob, anchor):
    """Every printable NUL-separated string in the table containing `anchor`."""
    i = blob.find(anchor)
    if i < 0:
        return []
    lo, hi = max(0, i - 1_500_000), min(len(blob), i + 1_500_000)
    out = []
    for s in blob[lo:hi].split(b"\x00"):
        if 2 < len(s) < 3000 and all(32 <= c < 127 or c >= 160 for c in s):
            out.append(s.decode("utf-8", "replace"))
    return out


def looks_like_tutorial(s, use_reject=True):
    """A popup body: a sentence, in English, long enough to be prose.

    Shape alone gets this wrong in both directions - the 140-character floor this used to have
    dropped the Totem and Mage Aura popups, which are one sentence each - so the real selection is
    the hand list in tutorial_keep_<game>.json and this only narrows the field for it.
    """
    if len(s) < 60 or s.count(" ") < 10:
        return False
    if not all(32 <= ord(c) < 127 for c in s):
        return False        # the table holds French, German, Spanish and Italian copies too
    if not re.match(r"^[A-Z]", s) or not re.search(r"[.!?]$", s.strip()):
        return False
    # REJECT is only a default sieve for when there is no hand list. An explicit list must win:
    # "You have unspent Karma. Are you sure..." is a real character-creation popup and was being
    # thrown out by the "are you sure" rule before the list ever got to see it.
    if use_reject and REJECT.search(s):
        return False
    if re.search(r"\{0\}|Cooldown:|\+\d+ AP|-\d+ HP|Key Attributes:", s):
        return False
    return True


def main():
    if not (ASSETS and os.path.exists(ASSETS)):
        sys.exit("usage: extract_tutorials.py <game> <path to resources.assets> [--write]")
    blob = open(ASSETS, "rb").read()
    strs = strings_around(blob, b"Karma represents the experience")
    if not strs:
        sys.exit("could not find the UI string table (anchor string missing)")
    keep = None
    if os.path.exists(HAND):
        keep = list(json.load(open(HAND)).get("keep") or [])
    cands = [s for s in dict.fromkeys(strs) if looks_like_tutorial(s, use_reject=keep is None)]
    out = {}
    for s in cands:
        text = re.sub(r"\s+", " ", s).strip()
        # Matched on a distinctive opening substring, so the list survives a wording tweak that a
        # hash would not - and reads as English rather than as sixteen md5s.
        if keep is not None and not any(text.startswith(k) or k in text for k in keep):
            continue
        out["tut_" + hashlib.md5(text.encode()).hexdigest()[:16]] = {
            "text": text, "speaker": "Tutorial", "kind": "helpscreen", "nonverbal": False,
        }
    print(f"[{GAME}] string table: {len(strs)} strings | {len(cands)} shaped like tutorials"
          f"{f' | {len(out)} kept by hand list' if keep is not None else ''}")
    if not WRITE:
        for k, v in list(out.items() or [(k, {'text': c}) for k, c in
                                         zip(range(6), cands[:6])])[:6]:
            print(f"   {str(v['text'])[:120]}")
        print("(dry run — pass --write to save)")
        return
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {OUT} ({len(out)} tutorials)")


if __name__ == "__main__":
    main()
