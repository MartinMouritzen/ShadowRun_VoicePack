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

    # Repeated lines. Branching dialogue says the same words at many nodes, so the lab shows and
    # generates only one of them; the others get their voice here by reusing that node's keeper.
    # Clips are named after the SOURCE take path below, so two nodes sharing a take share one ogg
    # automatically — this costs no extra disk and no extra generation.
    #
    # dupes.json is written by the Voice Lab (lab/tools/build_dupes.py) in the private repo. This
    # repo stays standalone on purpose: no file, no dedup, still a correct pack.
    dupes = jload_opt("dupes.json", {})
    aliases = dupes.get("aliases", {})

    def content_hash(name):
        p = os.path.join(DATA, name)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:16]

    stale_inputs = [n for n, fp in (dupes.get("_fingerprint") or {}).items()
                    if fp != content_hash(n)]
    if stale_inputs:
        print(f"  NOTE: dupes.json is older than {', '.join(sorted(stale_inputs))} — repeated "
              f"lines may be mapped from stale text. Re-run lab/tools/build_dupes.py --game "
              f"srr-{GAME}", file=sys.stderr)

    def pick(bucket, seg_key, allow_narrator):
        """A node's own keeper take, else the keeper of the node whose line it repeats."""
        canon = (aliases.get(bucket) or {}).get(seg_key)
        if canon is None and allow_narrator:
            canon = (aliases.get("narrator") or {}).get(seg_key)
        for k in (seg_key, canon):
            if not k:
                continue
            sel = selected(bucket, k)
            # plain narrator-owned GM lines live under 'narrator' even if char_id differs
            if sel is None and allow_narrator:
                sel = selected("narrator", k)
            if sel:
                return sel
        return None

    # Build ordered clip lists per line
    lines = {}          # base_key -> [source_rel_mp3, ...] (ordered, only selected)
    stats = {"lines_total": 0, "lines_voiced": 0, "segments_voiced": 0, "missing_files": 0}

    # Template-variable variants. A line that says $(l.race) is shipped once per metatype under
    # "<key>#<variantId>"; the plugin resolves the playthrough's values, tries the matching key and
    # falls back to the plain key when that variant was never generated. Empty when the game has no
    # variants.json, which keeps this repo standalone.
    VARIANTS = jload_opt("variants.json", {}).get("segments") or {}
    stats["variant_clips"] = 0

    def process(char_id, line_list):
        for l in line_list:
            base_key = f'{l["c"]}_{l["n"]}'
            stats["lines_total"] += 1
            ordered = []
            keys = seg_keys(char_id, base_key, SEGS)
            vids = set()
            for _, seg_key in keys:
                vids |= set((VARIANTS.get(seg_key) or {}).get("v") or {})
            for bucket, seg_key in keys:
                b = char_id if bucket == "char_or_narr" else bucket
                sel = pick(b, seg_key, bucket == "char_or_narr")
                if sel:
                    if os.path.exists(os.path.join(AUDIO, *sel.split("/"))):
                        ordered.append(sel); stats["segments_voiced"] += 1
                    else:
                        stats["missing_files"] += 1
            if ordered:
                lines[base_key] = ordered
                stats["lines_voiced"] += 1
            for vid in sorted(vids):
                # Segments that do not vary reuse the generic clip, so a variant line is only as
                # long as the words that actually change.
                seq, whole = [], True
                for bucket, seg_key in keys:
                    b = char_id if bucket == "char_or_narr" else bucket
                    sel = (pick(b, f"{seg_key}#{vid}", bucket == "char_or_narr")
                           if vid in ((VARIANTS.get(seg_key) or {}).get("v") or {})
                           else pick(b, seg_key, bucket == "char_or_narr"))
                    if sel and os.path.exists(os.path.join(AUDIO, *sel.split("/"))):
                        seq.append(sel)
                    else:
                        whole = False; break
                if whole and seq and seq != ordered:
                    lines[f"{base_key}#{vid}"] = seq
                    stats["variant_clips"] += 1

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
            # A variable-bearing inspect ("The special today is a $(scene.CafeSpecial).") ships one
            # clip per value, keyed by the md5 of the RESOLVED sentence. The plugin expands the raw
            # text through the game's own substitution and hashes the result, so it needs to know
            # nothing about which variable this was or what its values are.
            ent = VARIANTS.get(key) or {}
            if ent.get("hashed"):
                voiced_any = False
                for vid, vtext in (ent.get("v") or {}).items():
                    vsel = selected("narrator", f"{key}#{vid}")
                    if vsel and os.path.exists(os.path.join(AUDIO, *vsel.split("/"))):
                        h = "insp_" + hashlib.md5(vtext.encode("utf-8")).hexdigest()[:16]
                        lines[h] = [vsel]
                        stats["variant_clips"] += 1
                        voiced_any = True
                if voiced_any and not sel:
                    stats["lines_voiced"] += 1

    # Barks AND screen narration: takes live under the "_barks" bucket keyed "bark_<md5(text)>".
    # The plugin hashes the runtime text the same way (DisplayTextOverActor / load screen /
    # epilogue hooks).
    #
    # A loadscreen or epilogue runs to several paragraphs, so the lab generates it one beat at a
    # time under "<key>~g<i>" and they are stitched back together here — the plugin plays a clip
    # list in order, with SegmentGap between. bark_segments.json (how many beats a bark should
    # have) is written by the private Voice Lab; without it the order is still recovered from the
    # take keys themselves, so this repo stays standalone, exactly like dupes.json.
    bark_doc = jload_opt("bark_segments.json", {})
    bark_beats = bark_doc.get("beats") or {}
    bark_stale = [n for n, fp in (bark_doc.get("_fingerprint") or {}).items()
                  if fp != content_hash(n)]
    if bark_stale:
        # Without a current beat count this cannot tell "all four paragraphs are voiced" from
        # "the last one is missing", so it stops trusting the file entirely and falls back to
        # whole-bark takes. Truncated narration must never be the failure mode.
        print(f"  NOTE: bark_segments.json is older than {', '.join(sorted(bark_stale))} — long "
              f"narration falls back to whole-bark takes. Reload the lab to rewrite it.",
              file=sys.stderr)
        bark_beats = {}
    bark_alias = bark_doc.get("aliases") or {}
    if bark_stale:
        bark_alias = {}
    if not bark_alias:
        # Standalone fallback (no lab-written file): at minimum, pair up whole barks that hold the
        # exact same words. extract_epilogue.py emits both an exact and a whitespace-collapsed key
        # for one text so a stray space can't lose the ending, and both must play.
        same = {}
        for k, b in jload_opt("barks.json", {}).items():
            same.setdefault(re.sub(r"\s+", " ", (b.get("text") or "")).strip(), []).append(k)
        bark_alias = {k: ks[0] for ks in same.values() if len(ks) > 1 for k in ks[1:]}

    def on_disk(sel):
        return sel if sel and os.path.exists(os.path.join(AUDIO, *sel.split("/"))) else None

    def bark_clip(seg_key):
        """This key's keeper, else the keeper of the key it says the same words as."""
        return on_disk(selected("_barks", seg_key)) or on_disk(selected("_barks", bark_alias.get(seg_key)))

    beat_takes = {}          # base bark key -> highest beat index that has a take
    for k in takes.get("_barks", {}):
        base, _, suffix = k.partition("~")
        n = int(suffix[1:]) + 1 if suffix[:1] == "g" and suffix[1:].isdigit() else 0
        beat_takes[base] = max(beat_takes.get(base, 0), n)

    partial_barks = []
    # Every bark that could have a clip: one with takes of its own, one the lab split into beats,
    # and one that inherits another's words.
    keys = set(beat_takes) | set(bark_beats) | {k.split("~")[0] for k in bark_alias}
    for key in sorted(keys):
        stats["lines_total"] += 1
        expected = len(bark_beats.get(key) or ())
        nbeats = expected if expected > 1 else beat_takes.get(key, 0)
        ordered = [c for c in (bark_clip(f"{key}~g{i}") for i in range(nbeats)) if c]
        whole = bark_clip(key)
        if nbeats and len(ordered) < nbeats:
            # Half a load screen is worse than none: it stops mid-story with no way for the player
            # to tell whether the mod broke. Prefer the complete one-piece take when the bark was
            # voiced before it got split; otherwise ship nothing and say so.
            if whole:
                ordered = [whole]
            elif ordered:
                partial_barks.append(f"{key} ({len(ordered)}/{nbeats} beats)")
                ordered = []
        elif not nbeats:
            ordered = [whole] if whole else []
        if ordered:
            lines[key] = ordered
            stats["lines_voiced"] += 1; stats["segments_voiced"] += len(ordered)
    if partial_barks:
        print(f"  NOTE: {len(partial_barks)} narration bark(s) are only PARTLY voiced and were "
              f"SKIPPED (voice the remaining beats in the lab):", file=sys.stderr)
        for p in partial_barks[:20]:
            print(f"    {p}", file=sys.stderr)

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

    # Transcode unique source mp3s -> ogg (hash-named, deterministic, deduped), loudness-normalized.
    # EL v3 speech averages ~-17 LUFS integrated with true peaks already near 0 dBFS, which is
    # audibly quieter than the game's own (compressed) audio and can't be fixed with plain gain.
    # Two-pass ffmpeg loudnorm: pass 1 measures, pass 2 normalizes to LN_I/LN_TP (linear gain when
    # the measurement is usable, dynamic otherwise). Clips whose measurement fails fall back to the
    # old plain transcode. NOTE: existing clips/*.ogg are reused as a cache — after changing LN_*
    # targets, delete voicepack/<game>/clips/ to re-normalize everything.
    LN_I, LN_TP, LN_LRA = -14.0, -1.5, 11.0
    os.makedirs(CLIPS, exist_ok=True)

    def transcode(src, ogg_abs):
        src_abs = os.path.join(AUDIO, *src.split("/"))
        ln = f"loudnorm=I={LN_I}:TP={LN_TP}:LRA={LN_LRA}"
        try:
            m = subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostats", "-i", src_abs,
                 "-af", ln + ":print_format=json", "-f", "null", "-"], capture_output=True)
            txt = m.stderr.decode(errors="replace")
            j = json.loads(txt[txt.rindex("{"):])
            if float(j["input_i"]) > -70:   # measurable audio -> transparent linear normalization
                ln += (f":measured_I={j['input_i']}:measured_TP={j['input_tp']}"
                       f":measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}"
                       f":offset={j['target_offset']}:linear=true")
        except Exception:
            ln = None   # unmeasurable (ultra-short/silent) -> plain transcode, no loudnorm
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src_abs]
        if ln: cmd += ["-af", ln]
        cmd += ["-ac", "1", "-c:a", "libvorbis", "-q:a", "5", "-ar", "44100", ogg_abs]
        return subprocess.run(cmd, capture_output=True)

    src_to_ogg = {}
    jobs = []
    for src_list in lines.values():
        for src in src_list:
            if src in src_to_ogg:
                continue
            h = hashlib.sha1(src.encode("utf-8")).hexdigest()[:16]
            ogg_rel = f"clips/{h}.ogg"
            src_to_ogg[src] = ogg_rel
            ogg_abs = os.path.join(OUT, ogg_rel)
            if not os.path.exists(ogg_abs):
                jobs.append((src, ogg_rel, ogg_abs))
    if jobs:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as pool:
            for (src, ogg_rel, ogg_abs), r in zip(jobs, pool.map(lambda a: transcode(a[0], a[2]), jobs)):
                if r.returncode != 0:
                    print(f"WARN transcode failed for {src}: {r.stderr.decode()[:200]}", file=sys.stderr)
                    src_to_ogg.pop(src, None)

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

    # Prune cache oggs no longer referenced by any line (replaced retakes, deleted takes) —
    # build_dist.sh copies clips/ wholesale, so stale files would ship to users otherwise.
    referenced = {rel.split("/", 1)[1] for rel in src_to_ogg.values()}
    stale = [f for f in os.listdir(CLIPS) if f.endswith(".ogg") and f not in referenced]
    for f in stale:
        os.remove(os.path.join(CLIPS, f))
    if stale:
        print(f"  pruned {len(stale)} stale cached clip(s) not referenced by the manifest")

    total_mb = sum(os.path.getsize(os.path.join(OUT, "clips", f))
                   for f in os.listdir(CLIPS)) / 1e6 if os.path.isdir(CLIPS) else 0
    print(f"voicepack: {len(manifest_lines)} voiced nodes, "
          f"{len(src_to_ogg)} unique clips ({total_mb:.1f} MB)")
    if stats.get("variant_clips"):
        print(f"  variants: {stats['variant_clips']} variant line(s) shipped "
              f"(race / gender / scene-string alternatives)")
    print(f"  lines total={stats['lines_total']} voiced={stats['lines_voiced']} "
          f"segments={stats['segments_voiced']} missing_files={stats['missing_files']}")
    # Assert no MP3 leaked into the pack
    bad = [f for f in os.listdir(CLIPS) if not f.endswith(".ogg")]
    if bad:
        print(f"ERROR: non-ogg files in clips/: {bad[:5]}", file=sys.stderr); sys.exit(1)
    print(f"  wrote {os.path.join(OUT, 'voicepack.json')}")

if __name__ == "__main__":
    main()
