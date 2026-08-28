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
    reachable_extra = set()   # keys on surfaces the orphan check below cannot derive from lines
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
                    if vid in ((VARIANTS.get(seg_key) or {}).get("v") or {}):
                        # A repeated line is generated once, so a node that is a copy has no
                        # variant takes of its own — it inherits the canonical node's, exactly as
                        # it already inherits the generic clip. Dedup groups now carry the variant
                        # texts in their identity, so the canonical is guaranteed to say the same
                        # words in every variant.
                        canon = (aliases.get(b) or {}).get(seg_key)
                        if canon is None and bucket == "char_or_narr":
                            canon = (aliases.get("narrator") or {}).get(seg_key)
                        sel = pick(b, f"{seg_key}#{vid}", bucket == "char_or_narr")
                        if not sel and canon:
                            sel = pick(b, f"{canon}#{vid}", bucket == "char_or_narr")
                    else:
                        sel = pick(b, seg_key, bucket == "char_or_narr")
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

    # Help-screen tutorials: keyed "tut_<md5(text)>" under the narrator bucket, matching what the
    # plugin hashes off the popup at runtime. A separate surface from the scene popups in
    # barks.json - same idea, different origin.
    tut_path = os.path.join(DATA, "tutorials.json")
    if os.path.exists(tut_path):
        for key in json.load(open(tut_path)):
            stats["lines_total"] += 1
            sel = selected("narrator", key)
            if sel and os.path.exists(os.path.join(AUDIO, *sel.split("/"))):
                lines[key] = [sel]
                stats["lines_voiced"] += 1; stats["segments_voiced"] += 1
                reachable_extra.add(("narrator", key))
                # A popup can append a live counter to its body - the Etiquette screen ends
                # "...can only be chosen once. 0/1" - so the exact hash never matches at runtime.
                # A second key over the first 90 characters is immune to anything appended.
                body = (json.load(open(tut_path))[key].get("text") or "")
                head = re.sub(r"\s+", " ", body).strip()[:90]
                if len(head) >= 40:
                    lines["tutp_" + hashlib.md5(head.encode("utf-8")).hexdigest()[:16]] = [sel]

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
    # NOT included: playing a whole-line take where the line is now interleaved would speak the
    # narration and the speech in the wrong order. Classified below into harmless and harmful.
    reachable = set()
    for ch in chars["characters"]:
        for l in ch.get("lines", []):
            bk = f'{l["c"]}_{l["n"]}'
            for bucket, sk in seg_keys(ch["id"], bk, SEGS):
                b = ch["id"] if bucket == "char_or_narr" else bucket
                reachable.add((b, sk))
                reachable.add(("narrator", sk))
                # A variant take is reached through its own key, not the segment's, so without this
                # every one of them reads as an orphan from a dead segmentation.
                for vid in (VARIANTS.get(sk) or {}).get("v") or {}:
                    reachable.add((b, f"{sk}#{vid}"))
                    reachable.add(("narrator", f"{sk}#{vid}"))
    for l in chars.get("narrator", {}).get("lines", []):
        reachable.add(("narrator", f'{l["c"]}_{l["n"]}'))
    for k in takes.get("_barks", {}):
        reachable.add(("_barks", k))                       # bark takes are intentionally reachable
    if os.path.exists(inspect_path):                       # inspect takes live under narrator, keyed insp_<md5>
        for k in json.load(open(inspect_path)):
            reachable.add(("narrator", k))
            for vid in (VARIANTS.get(k) or {}).get("v") or {}:
                reachable.add(("narrator", f"{k}#{vid}"))
    reachable |= reachable_extra
    orphans = [(b, k) for b, lns in takes.items() for k, v in lns.items()
               if v.get("selected") and (b, k) not in reachable]

    # Two very different things end up in that list, and lumping them together made the message
    # actively misleading: it said "regenerate these lines" about 55 lines that were already voiced
    # correctly, and buried the 7 that genuinely shipped nothing.
    #
    #   SUPERSEDED   The line USED to be one whole-line take; it is now split, every ~cN segment has
    #                its own keeper, and the pack ships those. The base-key take is just a leftover
    #                keeper on a key nothing reads any more. Nothing to do - and deliberately not
    #                "fixed" by clearing the flag, because a line that later becomes unsegmented
    #                again would then have no keeper at all.
    #   STRANDED     Nothing ships for this line. Real audio gap, needs attention. The seven
    #                $(scene.CafeSpecial) inspect variants sat here because variants.json had been
    #                rebuilt without SRR_CONTENT_PACKS, so their value set was missing entirely.
    #
    # "Does the pack ship this line?" is exactly `base key in lines`, so classify on that rather
    # than re-deriving the segmentation a second way.
    superseded = [(b, k) for b, k in orphans if k.split("#")[0].split("~")[0] in lines]
    stranded = [(b, k) for b, k in orphans if (b, k) not in set(superseded)]
    if superseded:
        print(f"  note: {len(superseded)} superseded whole-line keeper(s) on pre-split keys — their "
              f"lines ship from the segment takes, nothing to do.", file=sys.stderr)
    if stranded:
        print(f"  WARNING: {len(stranded)} selected take(s) are STRANDED — nothing ships for these "
              f"lines (regenerate, or check variants.json / line_segments.json is current):",
              file=sys.stderr)
        for b, k in stranded[:20]:
            print(f"    {b} / {k}", file=sys.stderr)

    # Transcode unique source mp3s -> ogg (hash-named, deterministic, deduped), loudness-matched.
    #
    # We do NOT use ffmpeg's loudnorm here, and that is deliberate. loudnorm honours linear=true
    # only when the whole gain fits under the true-peak ceiling; otherwise it silently switches to
    # DYNAMIC mode, a block-based gain rider that reshapes the envelope of the entire clip. Asking
    # for I=-14 was asking for exactly that: EL v3 output is already peak-normalised (median true
    # peak -1.2 dBFS) so the median take had ~0 dB of headroom but needed +3.5 dB, and 75% of takes
    # came out dynamically compressed. It cost real quality and STILL left a 7.6 LU spread across
    # the shipped pack, because loudnorm cannot boost a quiet clip past the ceiling either.
    #
    # Instead: one flat gain (perfectly transparent) plus a look-ahead peak limiter that only ever
    # touches samples which would breach the ceiling. At the SAME loudness as the old loudnorm pack
    # this measures 1.7x more transparent on average and 2.4x better worst-case, so the compression
    # was never the price of being loud; loudnorm was just the wrong tool for it.
    #
    # On the target. This first shipped at -18, justified by measuring Dragonfall's own audio at a
    # -21.8 LUFS median. That measurement was over the WRONG POPULATION: the sample was dominated by
    # ambient loops and one-shot SFX (typing at -47 LUFS, insects at -46), none of which compete with
    # dialogue. Music does, and the soundtrack measures -12.5 to -13.0 LUFS, with the loud ambient
    # beds at -16.4 (p90) and layering on top of each other. At -18 the voices sat ~5 dB UNDER the
    # music and Martin had to strain to hear them in the real mix.
    #
    # -14 lands the pack at about -14.6 median, roughly 1.6 dB under the music instead of 5, and
    # matches the loudness of the pre-existing loudnorm pack while measuring cleaner than it. The
    # cost is honest and worth stating: loudness and evenness genuinely pull against each other,
    # because lifting a quiet take is the only operation that costs anything. -14 gives a ~4.5 LU
    # spread where -18 gave ~1.4. Louder was the right call because the plugin's Volume config is
    # clamped 0..1 by Unity, so players can turn voices DOWN but never UP: too quiet is the one
    # error nobody downstream can correct.
    #
    # MAX_LIMIT bounds how hard the limiter may work; a take needing more than that (a shout, a big
    # plosive) is left below target rather than squashed. Keeping its punch is the correct trade.
    #
    # NOTE: existing clips/*.ogg are reused as a cache — after changing any constant below, delete
    # voicepack/<game>/clips/ or nothing will be re-encoded. voicepack.stamp (written below) is what
    # makes sync_to_game.sh notice and re-install them.
    TARGET_I  = -14.0    # LUFS integrated
    # -1.5, not -1.0: alimiter bounds SAMPLE peaks, but Vorbis (like any lossy codec) can overshoot
    # on decode, and true (inter-sample) peak runs above sample peak besides. At a -1.0 ceiling a
    # couple of clips per pack measured just above 0 dBFS true peak, which Unity's mixer would clip.
    # 0.5 dB of extra headroom costs nothing audible and makes the pack provably peak-safe.
    CEILING   = -1.5     # dBFS, the limiter's ceiling
    MAX_LIMIT = 6.0      # dB; never ask the limiter for more gain reduction than this
    # q8, not q5 and not q10. q5 was a real second-generation loss (residual only ~23 dB below
    # signal); q10 measures far cleaner but Martin could not hear it against q5 in a level-matched
    # WAV comparison, and tripling a Nexus download for something nobody can hear is not a trade
    # worth making. q8 sits comfortably above the 128 kbps mp3 source, and matters more now that
    # gen_el.py requests 192 kbps: at q5 that source upgrade would be thrown away here.
    VORBIS_Q  = "8"
    os.makedirs(CLIPS, exist_ok=True)

    def transcode(src, ogg_abs):
        src_abs = os.path.join(AUDIO, *src.split("/"))
        af = None
        try:
            m = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-i", src_abs,
                 "-af", "loudnorm=I=%s:TP=%s:LRA=11:print_format=json" % (TARGET_I, CEILING),
                 "-f", "null", "-"], capture_output=True)
            txt = m.stderr.decode(errors="replace")
            j = json.loads(txt[txt.rindex("{"):])
            src_i, src_tp = float(j["input_i"]), float(j["input_tp"])
            if src_i > -70:                      # measurable audio
                headroom = CEILING - src_tp      # gain available before the limiter does anything
                gain = min(TARGET_I - src_i, headroom + MAX_LIMIT)
                af = ("volume=%.2fdB,alimiter=limit=%.4f:attack=5:release=100:level=disabled"
                      % (gain, 10 ** (CEILING / 20.0)))
        except Exception:
            af = None   # unmeasurable (ultra-short/silent) -> plain transcode, no level change
        cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", src_abs]
        if af: cmd += ["-af", af]
        cmd += ["-ac", "1", "-c:a", "libvorbis", "-q:a", VORBIS_Q, "-ar", "44100", ogg_abs]
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

    # Bark gates. A handful of vanilla triggers redraw their floating text after EVERY conversation
    # that ends on the map, because the engine's "On Conversation Complete" event takes no
    # conversation parameter and the trigger's conditions never stop being true. Silent in vanilla
    # (the bubble is anchored to an actor who is off-camera by then), but a voiced line the player
    # hears over and over. bark_gates.json names the conversation each such bark is meant to follow.
    # Only gates whose bark actually has clips are emitted — a gate for an unvoiced bark is dead
    # weight in the pack and would hide a keying mistake instead of showing it.
    gate_doc = jload_opt("bark_gates.json", {})
    gates = {}
    for gkey, g in (gate_doc.get("gates") or {}).items():
        after = g.get("afterConvo")
        ids = [after] if isinstance(after, str) else list(after or ())
        ids = [i for i in ids if i]
        if not ids:
            print(f"  WARN bark gate {gkey} names no conversation — ignored", file=sys.stderr)
            continue
        if gkey not in manifest_lines:
            print(f"  NOTE bark gate {gkey} has no voiced clips — gate not emitted")
            continue
        gates[gkey] = ids

    os.makedirs(OUT, exist_ok=True)

    # Encoder fingerprint. Clip files are named sha1(SOURCE TAKE PATH), so a re-encode with
    # different settings produces the SAME filename holding DIFFERENT audio. sync_to_game.sh
    # installs clips by "missing by name", which is fast and was correct while these settings never
    # moved; the moment they do, every already-installed clip silently keeps its old encoding and
    # the game plays audio the pack no longer contains. (That is exactly what happened on the
    # -14-loudnorm -> -18-flat-gain change: sync reported SYNCED in 1s having copied nothing.)
    # Writing the settings here lets the installer notice and force a full copy.
    with open(os.path.join(OUT, "voicepack.stamp"), "w", newline="\n") as f:
        f.write("target_i=%s ceiling=%s max_limit=%s vorbis_q=%s\n"
                % (TARGET_I, CEILING, MAX_LIMIT, VORBIS_Q))
    manifest = {"version": 1, "game": f"srr-{GAME}", "lines": manifest_lines, "gates": gates}
    with open(os.path.join(OUT, "voicepack.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    # TSV index for the plugin (net35 has no good JSON parser). One line per node:
    #   <convoId>_<nodeIndex>\t<clip1>\t<clip2>...
    with open(os.path.join(OUT, "voicepack.index"), "w", newline="\n") as f:
        f.write("# SRR voicepack index v1 — key<TAB>clip<TAB>clip...\n")
        for k in sorted(manifest_lines):
            f.write(k + "\t" + "\t".join(manifest_lines[k]) + "\n")

    # Gates ride in their own TSV rather than in voicepack.index, so an older plugin reading the
    # index cannot mistake a gate row for a line key with a clip named after a conversation.
    # Always written, even empty: sync_to_game.sh and build_dist.sh then copy it unconditionally.
    with open(os.path.join(OUT, "voicepack.gates"), "w", newline="\n") as f:
        f.write("# SRR voicepack bark gates v1 — barkKey<TAB>convoId<TAB>convoId...\n")
        for k in sorted(gates):
            f.write(k + "\t" + "\t".join(gates[k]) + "\n")

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
