#!/usr/bin/env python3
"""Validate a built voice pack's indexes, clip set, and decoded audio characteristics.

Usage: audit_voicepack.py [dms|dragonfall|hk] [--skip-audio] [--json]

This is deliberately separate from build_voicepack.py: a complete decoded-audio pass is useful
as a release gate, but too slow to impose on every iterative pack rebuild.
"""
import concurrent.futures
import json
import math
import os
import re
import shutil
import subprocess
import sys

GAME = next((a for a in sys.argv[1:] if not a.startswith("-")), "dms")
if GAME not in ("dms", "dragonfall", "hk"):
    sys.exit(f"ERROR: unknown game '{GAME}'")
AS_JSON = "--json" in sys.argv
SKIP_AUDIO = "--skip-audio" in sys.argv
ROOT = os.path.join(os.path.dirname(__file__), "..")
PACK = os.path.join(ROOT, "voicepack", GAME)
MANIFEST = os.path.join(PACK, "voicepack.json")
INDEX = os.path.join(PACK, "voicepack.index")
CLIPS = os.path.join(PACK, "clips")


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def read_index(path):
    out = {}
    duplicates = []
    for lineno, raw in enumerate(open(path, encoding="utf-8"), 1):
        raw = raw.rstrip("\n")
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) < 2:
            fail(f"{path}:{lineno}: missing tab separator")
        key, values = fields[0], fields[1:]
        if key in out:
            duplicates.append(key)
        out[key] = values
    return out, duplicates


def audio_stats(rel):
    path = os.path.join(PACK, *rel.split("/"))
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-af",
         "astats=measure_perchannel=none", "-f", "null", "-"],
        capture_output=True, text=True)
    log = proc.stderr
    def last_float(pattern):
        vals = re.findall(pattern, log)
        try:
            return float(vals[-1]) if vals else None
        except ValueError:
            return None
    duration = None
    times = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", log)
    if times:
        h, m, s = times[-1]
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    peak = last_float(r"Peak level dB:\s*(-?(?:inf|\d+(?:\.\d+)?))")
    rms = last_float(r"RMS level dB:\s*(-?(?:inf|\d+(?:\.\d+)?))")
    return {"clip": rel, "ok": proc.returncode == 0, "duration": duration,
            "peakDb": peak, "rmsDb": rms}


def quantile(values, q):
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] if lo == hi else values[lo] + (values[hi] - values[lo]) * (pos - lo)


if not os.path.exists(MANIFEST) or not os.path.exists(INDEX):
    fail(f"voice pack is not built at {PACK}")
manifest_doc = json.load(open(MANIFEST, encoding="utf-8"))
manifest = manifest_doc.get("lines") or {}
index, duplicate_keys = read_index(INDEX)
refs = {rel for seq in manifest.values() for rel in seq}
disk = {"clips/" + name for name in os.listdir(CLIPS) if name.endswith(".ogg")}
findings = {
    "manifestIndexMismatch": manifest != index,
    "duplicateIndexKeys": sorted(set(duplicate_keys)),
    "missingClips": sorted(refs - disk),
    "orphanClips": sorted(disk - refs),
    "audio": [],
}

stats = []
if not SKIP_AUDIO:
    if not shutil.which("ffmpeg"):
        fail("ffmpeg not found on PATH")
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        stats = list(pool.map(audio_stats, sorted(refs & disk)))
    for row in stats:
        if not row["ok"]:
            findings["audio"].append({**row, "reason": "decode failed"})
        elif row["duration"] is None or row["duration"] < 0.2:
            findings["audio"].append({**row, "reason": "missing or implausibly short duration"})
        elif row["peakDb"] is None or row["peakDb"] > -0.05:
            findings["audio"].append({**row, "reason": "missing peak measurement or clipping risk"})
        elif row["rmsDb"] is None or row["rmsDb"] < -35.0:
            findings["audio"].append({**row, "reason": "missing RMS measurement or near-silent audio"})

summary = {
    "game": GAME, "lines": len(manifest), "clips": len(refs),
    "decoded": len(stats), "findings": findings,
    "durationSec": {"p05": quantile([r["duration"] for r in stats], .05),
                    "median": quantile([r["duration"] for r in stats], .5),
                    "p95": quantile([r["duration"] for r in stats], .95),
                    "max": max((r["duration"] for r in stats if r["duration"] is not None),
                               default=None)},
    "rmsDb": {"p01": quantile([r["rmsDb"] for r in stats], .01),
              "median": quantile([r["rmsDb"] for r in stats], .5),
              "p99": quantile([r["rmsDb"] for r in stats], .99)},
    "maxPeakDb": max((r["peakDb"] for r in stats if r["peakDb"] is not None), default=None),
}
bad = (findings["manifestIndexMismatch"] or findings["duplicateIndexKeys"] or
       findings["missingClips"] or findings["orphanClips"] or findings["audio"])
if AS_JSON:
    print(json.dumps(summary, indent=2, ensure_ascii=False))
else:
    print(f"[{GAME}] {len(manifest)} indexed line(s), {len(refs)} referenced clip(s), "
          f"{len(stats)} decoded")
    print(f"  manifest/index: {'MISMATCH' if findings['manifestIndexMismatch'] else 'identical'}; "
          f"missing {len(findings['missingClips'])}; orphan {len(findings['orphanClips'])}; "
          f"audio findings {len(findings['audio'])}")
    if stats:
        d, r = summary["durationSec"], summary["rmsDb"]
        print(f"  duration p05/median/p95/max: {d['p05']:.2f}/{d['median']:.2f}/"
              f"{d['p95']:.2f}/{d['max']:.2f}s")
        print(f"  RMS p01/median/p99: {r['p01']:.2f}/{r['median']:.2f}/{r['p99']:.2f} dB; "
              f"max peak {summary['maxPeakDb']:.3f} dB")
sys.exit(1 if bad else 0)
