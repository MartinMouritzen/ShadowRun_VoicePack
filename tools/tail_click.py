#!/usr/bin/env python3
"""Find and fix end-of-clip truncation clicks in generated takes.

The provider hands back speech trimmed hard against the last spoken sample, so a clip
often ENDS while the waveform is still well away from zero. That step straight down to
silence is a broadband click, and because the source is MP3 the encoder smears the
transient backwards across the final MDCT window -- which is why it is heard as a few
milliseconds of crackle/static rather than as a clean tick.

Detection is not perceptual guesswork: the defect IS the step, so we measure it directly
as the sample value where the audio stops. The fix is a short fade-out, NOT a snip --
snipping only moves the cut to a different non-zero sample (and can eat the tail of a
word), whereas an 8 ms ramp removes the discontinuity without removing any content.

  scan:  python3 tools/tail_click.py scan <game> [--all-takes] [--json out.json] [--top N]
  fix:   python3 tools/tail_click.py fix  <game> --threshold -24 [--dry-run] [--no-backup]
"""
import argparse, json, os, re, shutil, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.join(os.path.dirname(HERE), "app")

# Samples quieter than this are treated as digital silence / decoder padding, not audio.
SILENCE_FLOOR = 10 ** (-80 / 20)
FADE_S        = 0.060     # 60 ms, chosen by ear (see FADE NOTE below)
# FADE NOTE: 8 ms is enough to kill the step itself, and for a clip that ends on a normal quiet
# decay it is inaudible. But a minority of clips are cut off mid-word at full voice, and there an
# 8 ms ramp still reads as a chop -- 60 ms reads as a decay instead. 60 ms is inaudible on the
# clips that did not need it, so it is used everywhere rather than branching on clip class.
MAX_FADE_FRAC = 0.25      # never fade more than a quarter of a clip (guards very short takes)
SEG_FADE_S    = 0.008     # non-final segments: another ~g clip follows a beat later, so the ear is
                          # still inside the sentence. 60 ms there is heard as the narrator swallowing
                          # a word at every join; 8 ms is enough to kill the step and stays inaudible.
BACKUP_DIR    = "_preclickfix"


def decode(path, sr=None):
    """Decode to mono float32 at the file's native rate (or `sr`). Returns (rate, samples)."""
    if sr is None:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                            "-show_entries", "stream=sample_rate", "-of", "csv=p=0", path],
                           capture_output=True, text=True)
        sr = int(p.stdout.strip() or 44100)
    p = subprocess.run(["ffmpeg", "-v", "quiet", "-i", path, "-f", "f32le", "-ac", "1",
                        "-ar", str(sr), "-"], stdout=subprocess.PIPE)
    return sr, np.frombuffer(p.stdout, dtype="<f4").astype(np.float64)


def measure(path):
    """Where does the audio stop, and how loud is it when it does?"""
    sr, x = decode(path)
    if len(x) == 0:
        return None
    live = np.where(np.abs(x) > SILENCE_FLOOR)[0]
    if len(live) == 0:
        return None
    end = int(live[-1])                       # last sample that is actually audio
    step = abs(x[end])                        # the discontinuity: this value -> silence
    env  = float(np.abs(x[max(0, end - int(0.001 * sr)): end + 1]).max())
    db = lambda v: 20 * np.log10(max(float(v), 1e-12))
    return {
        "file": path,
        "sr": sr,
        "dur": len(x) / sr,
        "audio_end_s": (end + 1) / sr,        # sample-accurate; container duration is NOT reliable
        "trail_pad_ms": (len(x) - 1 - end) / sr * 1000.0,
        "step_db": db(step),                  # primary metric
        "env_db": db(env),                    # how loud the last millisecond is, for context
    }


def fix_file(path, out_path, audio_end_s, fade=FADE_S, bitrate="192k"):
    """Re-encode with a fade-out ending exactly where the audio stops.

    `st` is derived from the decoded sample count, never from the container duration --
    an MP3's reported duration includes encoder padding, so a duration-derived fade start
    can land past the real end and silently do nothing.
    """
    fade = min(fade, audio_end_s * MAX_FADE_FRAC)
    st = max(0.0, audio_end_s - fade)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path,
                        "-af", f"afade=t=out:st={st:.6f}:d={fade}:curve=hsin",
                        "-c:a", "libmp3lame", "-b:a", bitrate, out_path],
                       capture_output=True)
    return r.returncode == 0, r.stderr.decode(errors="replace")[:300]


SEG_RE = re.compile(r"^(.*)~g(\d+)(.*)$")


def nonfinal_segment_files(game):
    """Files whose line is a segment with a LATER segment after it (…~g0 when …~g1 exists).

    These are not clip endings at all -- the plugin plays the next segment a beat later -- so they
    get the short fade. Anything else (a whole line, a ~c variant, the last segment of a chain) is a
    real ending and gets the full one.
    """
    takes = json.load(open(os.path.join(APP, "data", game, "takes.json")))
    keys, out = {}, set()
    for cid, lines in takes.items():
        if isinstance(lines, dict):
            keys[cid] = set(k for k, v in lines.items() if isinstance(v, dict))
    for cid, lines in takes.items():
        if not isinstance(lines, dict):
            continue
        for lk, rec in lines.items():
            if not isinstance(rec, dict):
                continue
            m = SEG_RE.match(lk)
            if not m or f"{m.group(1)}~g{int(m.group(2)) + 1}{m.group(3)}" not in keys[cid]:
                continue
            for tk in rec.get("takes") or []:
                out.add(tk["file"])
    return out


def selected_takes(game, all_takes=False):
    data = os.path.join(APP, "data", game, "takes.json")
    takes = json.load(open(data))
    out = []
    for cid, lines in takes.items():
        if not isinstance(lines, dict):
            continue
        for lk, rec in lines.items():
            if not isinstance(rec, dict):
                continue
            sel = rec.get("selected")
            for tk in rec.get("takes") or []:
                if all_takes or tk.get("file") == sel:
                    out.append(tk["file"])
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "fix"])
    ap.add_argument("game")
    ap.add_argument("--all-takes", action="store_true", help="not just the selected take per line")
    ap.add_argument("--threshold", type=float, default=-30.0,
                    help="flag/fix clips whose LEVEL AT THE CUT (env_db) exceeds this")
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--jobs", type=int, default=3, help="parallel ffmpeg workers (keep low; this is CPU-heavy)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-json", help="reuse a previous scan's --json output instead of re-measuring")
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args()

    audio = os.path.join(APP, "audio", a.game)
    if a.from_json:
        res = json.load(open(a.from_json))
        print(f"{len(res)} clips (from {a.from_json})", file=sys.stderr)
    else:
        rels = selected_takes(a.game, a.all_takes)
        paths = [(r, os.path.join(audio, *r.split("/"))) for r in rels]
        paths = [(r, p) for r, p in paths if os.path.exists(p)]
        print(f"{len(paths)} clips", file=sys.stderr)

        from concurrent.futures import ThreadPoolExecutor
        res = []
        with ThreadPoolExecutor(max_workers=a.jobs) as pool:
            for rel, m in zip([r for r, _ in paths], pool.map(lambda rp: measure(rp[1]), paths)):
                if m:
                    m["rel"] = rel
                    res.append(m)

    res.sort(key=lambda m: -m["env_db"])
    # Flag on env_db (the signal level over the last millisecond), NOT step_db (the single final
    # sample). The final sample can land near a zero crossing by luck while the waveform around it
    # is still loud, so step_db UNDER-reports the click: across Dragonfall env_db runs a median
    # 5.8 dB and a p90 19 dB above step_db. A take that measured step -24.3 (under a -24 step
    # cutoff) but env -19.8 was still plainly audible, which is what exposed this.
    flagged = [m for m in res if m["env_db"] > a.threshold]

    if a.cmd == "scan":
        arr = np.array([m["env_db"] for m in res])
        print(f"\nend-of-audio step, {len(res)} clips:")
        for p in (50, 75, 90, 95, 99, 100):
            print(f"  p{p:<3d} {np.percentile(arr, p):7.1f} dBFS")
        for t in (-30, -24, -20, -15, -12, -10):
            n = (arr > t).sum()
            print(f"  above {t:4d} dBFS: {n:5d}  ({n / len(arr) * 100:5.2f}%)")
        print(f"\nworst {a.top}:")
        for m in res[:a.top]:
            print(f"  env {m['env_db']:7.1f} step {m['step_db']:7.1f} dBFS  {m['dur']:6.2f}s  {m['rel']}")
        if a.json:
            json.dump(res, open(a.json, "w"), indent=1)
            print(f"\nwrote {a.json}", file=sys.stderr)
        return

    print(f"{len(flagged)} clips above {a.threshold} dBFS", file=sys.stderr)
    if a.dry_run:
        for m in flagged[:a.top]:
            print(f"  would fix env {m['env_db']:7.1f} dBFS  {m['rel']}")
        return

    seg = nonfinal_segment_files(a.game)
    print(f"  ({len(seg & {m['rel'] for m in flagged})} of them are non-final segments -> {SEG_FADE_S*1000:.0f} ms fade)",
          file=sys.stderr)
    def do_one(m):
        # Everything in here is best-effort per file. The lab is a live process writing this same
        # take store: regenerating a line in the UI writes a NEW timestamped file and drops the old
        # one, so a path measured a minute ago can be gone by the time we reach it. That is normal,
        # not an error -- but it used to raise out of the worker, and pool.map re-raises on the
        # first failure, so ONE regenerated line aborted the entire sweep with thousands of clips
        # left untouched.
        try:
            return _do_one(m)
        except Exception as e:
            print(f"SKIP {m.get('rel')}: {e}", file=sys.stderr)
            return False

    def _do_one(m):
        src = os.path.join(audio, *m["rel"].split("/"))
        if not os.path.exists(src):
            return False        # regenerated or deleted since the scan; the new file gets its own pass
        if not a.no_backup:
            bak = os.path.join(audio, BACKUP_DIR, *m["rel"].split("/"))
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            if not os.path.exists(bak):
                shutil.copy2(src, bak)
        tmp = src + ".fix.mp3"
        good, err = fix_file(src, tmp, m["audio_end_s"],
                             fade=SEG_FADE_S if m["rel"] in seg else FADE_S)
        if not good:
            print(f"FAIL {m['rel']}: {err}", file=sys.stderr)
            if os.path.exists(tmp): os.remove(tmp)
            return False
        # verify the fade actually landed before replacing the original
        # Verify against the SAME bar we flagged on. This used to be a hardcoded -45, left over
        # from when flagging was step-based; once flagging moved to env at -30, a clip that faded
        # to -35 was "fixed by the flag's own definition" yet failed verification, so the good
        # result was thrown away and the CLICKY ORIGINAL kept. A stricter verify bar than the flag
        # bar can only ever discard fixes.
        chk = measure(tmp)
        if chk is None or chk["env_db"] > a.threshold:
            print(f"FAIL verify {m['rel']}: env still {chk and chk['env_db']:.1f} dBFS "
                  f"(needed <= {a.threshold})", file=sys.stderr)
            os.remove(tmp); return False
        os.replace(tmp, src)
        return True

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        results = list(pool.map(do_one, flagged))
    ok = sum(1 for r in results if r); bad = len(results) - ok
    print(f"fixed {ok}, failed {bad}", file=sys.stderr)


if __name__ == "__main__":
    main()
