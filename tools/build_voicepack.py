#!/usr/bin/env python3
"""Part A of the BepInEx plugin: export the lab's selected takes into a plugin-friendly voicepack.

Reads app/data/<game>/{characters,line_segments,takes}.json (game = dms|dragonfall|hk, argv[1],
default dms), resolves the ORDERED keeper clips per dialogue node (mirroring the lab's segsFor()
key logic exactly), transcodes each MP3 -> OGG Vorbis with ffmpeg, and writes
voicepack/<game>/voicepack.json + voicepack/<game>/clips/*.ogg.

voicepack.json schema:
  { "version":1, "game":"srr-<game>",
    "lines": { "<convoId>_<nodeIndex>": ["clips/<hash>.ogg", ...ordered...], ... } }

Only lines with at least one selected keeper appear. Narrator/character ordering is encoded as
list order; the plugin just plays the list. Deterministic output (hash-named clips, no timestamps).
"""
import json, os, re, sys, hashlib, subprocess, shutil

# Which game's pack to build (isolated per game). Usage: build_voicepack.py [dms|dragonfall|hk]
GAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dms"
if GAME not in ("dms", "dragonfall", "hk"):
    print(f"ERROR: unknown game '{GAME}' (expected dms|dragonfall|hk)", file=sys.stderr); sys.exit(1)

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "app", "data", GAME)     # per-game content + takes
AUDIO = os.path.join(ROOT, "app", "audio", GAME)   # per-game take audio
OUT = os.path.join(ROOT, "voicepack", GAME)        # per-game output pack
CLIPS = os.path.join(OUT, "clips")

def jload(name):
    return json.load(open(os.path.join(DATA, name)))

def jload_opt(name, default):
    p = os.path.join(DATA, name)
    return json.load(open(p)) if os.path.exists(p) else default

def seg_keys(char_id, base_key, SEGS):
    """Ordered [(bucket, segKey), ...] for a line — mirrors lab.html segsFor() + take-key derivation.
    bucket = 'narrator' for gm segments, else the owning character id."""
    if char_id == "narrator" or base_key not in SEGS:
        return [("char_or_narr", base_key)]  # plain line: single segment under the owning bucket
    raw = SEGS[base_key]
    nchar = sum(1 for s in raw if s["who"] == "char")
    out = []
    gi = ci = 0
    for s in raw:
        if s["who"] == "gm":
            out.append(("narrator", f"{base_key}~g{gi}")); gi += 1
        else:
            k = base_key if nchar == 1 else f"{base_key}~c{ci}"; ci += 1
            out.append((char_id, k))
    return out

def main():
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg not found on PATH", file=sys.stderr); sys.exit(1)
    chars = jload("characters.json")
    SEGS = jload_opt("line_segments.json", {})   # DMS-only manual multi-char segmentation
    takes = jload_opt("takes.json", {})          # empty until a game has generated takes

    def selected(bucket, seg_key):
        e = takes.get(bucket, {}).get(seg_key)
        return e.get("selected") if e else None

    # Build ordered clip lists per line
    lines = {}          # base_key -> [source_rel_mp3, ...] (ordered, only selected)
    stats = {"lines_total": 0, "lines_voiced": 0, "segments_voiced": 0, "missing_files": 0}

    def process(char_id, line_list):
        for l in line_list:
            base_key = f'{l["c"]}_{l["n"]}'
            stats["lines_total"] += 1
            ordered = []
            for bucket, seg_key in seg_keys(char_id, base_key, SEGS):
                b = char_id if bucket == "char_or_narr" else bucket
                sel = selected(b, seg_key)
                # plain narrator-owned GM lines live under 'narrator' bucket even if char_id differs
                if sel is None and bucket == "char_or_narr":
                    sel = selected("narrator", seg_key)
                if sel:
                    if os.path.exists(os.path.join(AUDIO, *sel.split("/"))):
                        ordered.append(sel); stats["segments_voiced"] += 1
                    else:
                        stats["missing_files"] += 1
            if ordered:
                lines[base_key] = ordered
                stats["lines_voiced"] += 1

    for ch in chars["characters"]:
        process(ch["id"], ch.get("lines", []))
    process("narrator", chars.get("narrator", {}).get("lines", []))

    # Inspect one-liners: keyed "insp_<md5>" under the narrator bucket; the plugin looks them up by
    # hashing the runtime inspectText. Add any that have a selected take.
    inspect_path = os.path.join(DATA, "inspect.json")
    if os.path.exists(inspect_path):
        for key in json.load(open(inspect_path)):
            stats["lines_total"] += 1
            sel = selected("narrator", key)
            if sel and os.path.exists(os.path.join(AUDIO, *sel.split("/"))):
                lines[key] = [sel]
                stats["lines_voiced"] += 1; stats["segments_voiced"] += 1

    # Combat barks: takes live under the "_barks" bucket keyed "bark_<md5(barkText)>". The plugin
    # hashes the runtime bark text the same way (DisplayTextOverActor hook).
    for key in list(takes.get("_barks", {}).keys()):
        stats["lines_total"] += 1
        sel = selected("_barks", key)
        if sel and os.path.exists(os.path.join(AUDIO, *sel.split("/"))):
            lines[key] = [sel]
            stats["lines_voiced"] += 1; stats["segments_voiced"] += 1

    # Detect selected takes that no current line-segment references (stale keys from a previous
    # segmentation model — e.g. a line that became interleaved after the take was made). These are
    # NOT included (playing them would be wrong order); report so the user can regenerate.
    reachable = set()
    for ch in chars["characters"]:
        for l in ch.get("lines", []):
            bk = f'{l["c"]}_{l["n"]}'
            for bucket, sk in seg_keys(ch["id"], bk, SEGS):
                reachable.add((ch["id"] if bucket == "char_or_narr" else bucket, sk))
                reachable.add(("narrator", sk))
    for l in chars.get("narrator", {}).get("lines", []):
        reachable.add(("narrator", f'{l["c"]}_{l["n"]}'))
    for k in takes.get("_barks", {}):
        reachable.add(("_barks", k))                       # bark takes are intentionally reachable
    if os.path.exists(inspect_path):                       # inspect takes live under narrator, keyed insp_<md5>
        for k in json.load(open(inspect_path)):
            reachable.add(("narrator", k))
    orphans = [(b, k) for b, lns in takes.items() for k, v in lns.items()
               if v.get("selected") and (b, k) not in reachable]
    if orphans:
        print(f"  NOTE: {len(orphans)} selected take(s) use an obsolete segmentation and were "
              f"SKIPPED (regenerate these lines in the lab):", file=sys.stderr)
        for b, k in orphans[:20]:
            print(f"    {b} / {k}", file=sys.stderr)

    # Transcode unique source mp3s -> ogg (hash-named, deterministic, deduped)
    os.makedirs(CLIPS, exist_ok=True)
    src_to_ogg = {}
    for src_list in lines.values():
        for src in src_list:
            if src in src_to_ogg:
                continue
            h = hashlib.sha1(src.encode("utf-8")).hexdigest()[:16]
            ogg_rel = f"clips/{h}.ogg"
            ogg_abs = os.path.join(OUT, ogg_rel)
            src_abs = os.path.join(AUDIO, *src.split("/"))
            if not os.path.exists(ogg_abs):
                r = subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", src_abs,
                     "-ac", "1", "-c:a", "libvorbis", "-q:a", "5", "-ar", "44100", ogg_abs],
                    capture_output=True)
                if r.returncode != 0:
                    print(f"WARN transcode failed for {src}: {r.stderr.decode()[:200]}", file=sys.stderr)
                    continue
            src_to_ogg[src] = ogg_rel

    manifest_lines = {k: [src_to_ogg[s] for s in v if s in src_to_ogg]
                      for k, v in lines.items()}
    manifest_lines = {k: v for k, v in manifest_lines.items() if v}

    os.makedirs(OUT, exist_ok=True)
    manifest = {"version": 1, "game": f"srr-{GAME}", "lines": manifest_lines}
    with open(os.path.join(OUT, "voicepack.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    # TSV index for the plugin (net35 has no good JSON parser). One line per node:
    #   <convoId>_<nodeIndex>\t<clip1>\t<clip2>...
    with open(os.path.join(OUT, "voicepack.index"), "w", newline="\n") as f:
        f.write("# SRR voicepack index v1 — key<TAB>clip<TAB>clip...\n")
        for k in sorted(manifest_lines):
            f.write(k + "\t" + "\t".join(manifest_lines[k]) + "\n")

    total_mb = sum(os.path.getsize(os.path.join(OUT, "clips", f))
                   for f in os.listdir(CLIPS)) / 1e6 if os.path.isdir(CLIPS) else 0
    print(f"voicepack: {len(manifest_lines)} voiced nodes, "
          f"{len(src_to_ogg)} unique clips ({total_mb:.1f} MB)")
    print(f"  lines total={stats['lines_total']} voiced={stats['lines_voiced']} "
          f"segments={stats['segments_voiced']} missing_files={stats['missing_files']}")
    # Assert no MP3 leaked into the pack
    bad = [f for f in os.listdir(CLIPS) if not f.endswith(".ogg")]
    if bad:
        print(f"ERROR: non-ogg files in clips/: {bad[:5]}", file=sys.stderr); sys.exit(1)
    print(f"  wrote {os.path.join(OUT, 'voicepack.json')}")

if __name__ == "__main__":
    main()
