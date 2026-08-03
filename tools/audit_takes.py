#!/usr/bin/env python3
"""Flag takes whose AUDIO LENGTH does not fit the text they were generated from.

Usage: audit_takes.py [dms|dragonfall|hk] [--all] [--json]
       --all   audit every take, not just the keeper of each segment

A take record stores the character count of the text that was submitted, so a clip whose duration
implies an impossible speaking rate did not come from that text: the generator truncated, returned
an empty/near-empty clip, or a bulk worker wrote one segment's audio under another segment's key.
Nothing else in the pipeline notices -- the manifest builder only checks that the file exists -- so
the wrong words ship and are only found by hearing them in game.

The band is calibrated on this pack: interactively generated takes sit at a median 15.4 chars/sec
with p05/p95 of 10.6/20.4, and 6..28 flags 0.2% of them while catching clips off by 3x and more.
It cannot catch a wrong clip that happens to be the right LENGTH, so a clean report is not proof
of correctness -- it is a floor, not a ceiling."""
import json, os, subprocess, sys

GAME = next((a for a in sys.argv[1:] if not a.startswith("-")), "dms")
if GAME not in ("dms", "dragonfall", "hk"): sys.exit(f"ERROR: unknown game '{GAME}'")
ALL, AS_JSON = "--all" in sys.argv, "--json" in sys.argv

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "app", "data", GAME)
AUDIO = os.path.join(ROOT, "app", "audio", GAME)
MIN_RATE, MAX_RATE = 6.0, 28.0     # chars/sec
MIN_CHARS = 15                     # below this, one drawn-out word makes the rate meaningless

def duration(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
        return float(out)
    except Exception:
        return None

def _load(name):
    p = os.path.join(DATA, name)
    return json.load(open(p)) if os.path.exists(p) else {}

# Non-speech barks are exempt: a sound effect has no chars/sec to speak of. The store's own
# 'nonverbal' flag misses some, so asterisk-wrapped SFX text ("*BEEP BEEP BEEP*") counts too.
BARKS = _load("barks.json")
def exempt(seg_key):
    b = BARKS.get(seg_key)
    if not b: return False
    return bool(b.get("nonverbal")) or (b.get("text", "").strip().startswith("*")
                                        and b.get("text", "").strip().endswith("*"))

takes = json.load(open(os.path.join(DATA, "takes.json")))
findings, checked, missing = [], 0, 0
for bucket, segs in takes.items():
    for seg_key, entry in segs.items():
        for tk in entry.get("takes", []):
            keeper = entry.get("selected") == tk["file"]
            if not (ALL or keeper): continue
            chars = tk.get("chars") or 0
            if chars < MIN_CHARS or exempt(seg_key): continue
            p = os.path.join(AUDIO, *tk["file"].split("/"))
            if not os.path.exists(p): missing += 1; continue
            d = duration(p)
            if d is None: continue
            checked += 1
            rate = chars / d if d > 0.05 else float("inf")
            if MIN_RATE <= rate <= MAX_RATE: continue
            findings.append({"bucket": bucket, "seg": seg_key, "keeper": keeper, "chars": chars,
                             "seconds": round(d, 2), "chars_per_sec": round(rate, 2),
                             "file": tk["file"],
                             "why": "clip too short for the text" if rate > MAX_RATE
                                    else "clip too long for the text"})

findings.sort(key=lambda f: (not f["keeper"], -abs(f["chars_per_sec"] - 15.4)))
if AS_JSON:
    print(json.dumps(findings, ensure_ascii=False, indent=1))
else:
    print(f"[{GAME}] checked {checked} take(s){' (keepers only)' if not ALL else ''}"
          + (f", {missing} missing audio file(s)" if missing else ""))
    print(f"{len(findings)} take(s) whose length does not fit their text "
          f"({sum(1 for f in findings if f['keeper'])} of them the current keeper):\n")
    for f in findings:
        print(f"  {'KEEPER' if f['keeper'] else '      '} {f['bucket']:<26} {f['seg']:<34} "
              f"{f['chars']:>4}ch {f['seconds']:>6.2f}s {f['chars_per_sec']:>7.2f}ch/s  {f['why']}")
sys.exit(1 if any(f["keeper"] for f in findings) else 0)
