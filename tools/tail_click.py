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
import argparse, json, os, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.join(os.path.dirname(HERE), "app")

# Samples quieter than this are treated as digital silence / decoder padding, not audio.
SILENCE_FLOOR = 10 ** (-80 / 20)
FADE_S        = 0.008     # 8 ms: inaudible as a level change, kills the step and most of the smear
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
    st = max(0.0, audio_end_s - fade)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path,
                        "-af", f"afade=t=out:st={st:.6f}:d={fade}:curve=hsin",
                        "-c:a", "libmp3lame", "-b:a", bitrate, out_path],
                       capture_output=True)
    return r.returncode == 0, r.stderr.decode(errors="replace")[:300]


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
    ap.add_argument("--threshold", type=float, default=-24.0, help="flag/fix clips whose step_db exceeds this")
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--jobs", type=int, default=3, help="parallel ffmpeg workers (keep low; this is CPU-heavy)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args()

    audio = os.path.join(APP, "audio", a.game)
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

    res.sort(key=lambda m: -m["step_db"])
    flagged = [m for m in res if m["step_db"] > a.threshold]

    if a.cmd == "scan":
        arr = np.array([m["step_db"] for m in res])
        print(f"\nend-of-audio step, {len(res)} clips:")
        for p in (50, 75, 90, 95, 99, 100):
            print(f"  p{p:<3d} {np.percentile(arr, p):7.1f} dBFS")
        for t in (-30, -24, -20, -15, -12, -10):
            n = (arr > t).sum()
            print(f"  above {t:4d} dBFS: {n:5d}  ({n / len(arr) * 100:5.2f}%)")
        print(f"\nworst {a.top}:")
        for m in res[:a.top]:
            print(f"  {m['step_db']:7.1f} dBFS  {m['dur']:6.2f}s  {m['rel']}")
        if a.json:
            json.dump(res, open(a.json, "w"), indent=1)
            print(f"\nwrote {a.json}", file=sys.stderr)
        return

    print(f"{len(flagged)} clips above {a.threshold} dBFS", file=sys.stderr)
    if a.dry_run:
        for m in flagged[:a.top]:
            print(f"  would fix {m['step_db']:7.1f} dBFS  {m['rel']}")
        return

    ok = bad = 0
    for m in flagged:
        src = os.path.join(audio, *m["rel"].split("/"))
        if not a.no_backup:
            bak = os.path.join(audio, BACKUP_DIR, *m["rel"].split("/"))
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            if not os.path.exists(bak):
                subprocess.run(["cp", "-p", src, bak], check=True)
        tmp = src + ".fix.mp3"
        good, err = fix_file(src, tmp, m["audio_end_s"])
        if not good:
            print(f"FAIL {m['rel']}: {err}", file=sys.stderr); bad += 1
            if os.path.exists(tmp): os.remove(tmp)
            continue
        # verify the fade actually landed before replacing the original
        chk = measure(tmp)
        if chk is None or chk["step_db"] > -45:
            print(f"FAIL verify {m['rel']}: step still {chk and chk['step_db']:.1f} dBFS", file=sys.stderr)
            os.remove(tmp); bad += 1
            continue
        os.replace(tmp, src)
        ok += 1
    print(f"fixed {ok}, failed {bad}", file=sys.stderr)


if __name__ == "__main__":
    main()
