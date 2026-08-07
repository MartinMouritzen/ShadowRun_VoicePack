#!/usr/bin/env python3
"""Drive the Voice Lab's /api/generate over a whole cast, in parallel, resumably.

Usage: gen_batch.py <lab-game-id> <charId>[,<charId>...] [--limit N] [--workers N] [--dry-run]
   e.g. gen_batch.py srr-dragonfall name_glory,name_eiger --workers 4

The lab server owns the Magnific credentials and the take store, so generation goes through it
rather than reimplementing the call here: one writer, one lock, one set of tokens. The job list is
rebuilt from disk on every run and anything that already has a take is skipped, so an interrupted
run is resumed simply by running it again.

Text is derived with lab/spoken.py - the same module the lab and the dedup use - so what is
generated is exactly what the lab shows. Repeated lines (dupes.json) and officially voiced lines
are skipped, because the pack gets those from the canonical take and the game's own VO.
"""
import argparse, json, math, os, queue, sys, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))     # ~/dev/voices
sys.path.insert(0, os.path.join(ROOT, "lab"))
import spoken                                                      # noqa: E402

LAB = os.environ.get("LAB_URL", "http://localhost:3719")
credits = lambda n: 2 * math.ceil(math.ceil(n / 5) / 2)            # verified against simulate_cost

ap = argparse.ArgumentParser()
ap.add_argument("game")
ap.add_argument("chars")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--dry-run", action="store_true")
# Auditions: force a voice and ignore "already has a take", so several candidates can be heard
# side by side on the same line in the lab, which is where the choice actually gets made.
ap.add_argument("--voice", help="voiceId to use instead of the character's casting, e.g. mag_537")
ap.add_argument("--voice-name", default="")
ap.add_argument("--redo", action="store_true", help="generate even for lines that already have takes")
ap.add_argument("--keys", help="comma-separated segment keys to restrict to")
a = ap.parse_args()
only = set(a.keys.split(",")) if a.keys else None

gcfg = json.load(open(os.path.join(ROOT, "games", a.game, "game.json")))
DATA = os.path.normpath(os.path.join(ROOT, "games", a.game, gcfg.get("dataDir") or "data"))
J = lambda n, d: json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d

chars = J("characters.json", {"characters": []})
segs, edits = J("line_segments.json", {}), J("text_edits.json", {})
directed, spoken_ov = J("directed.json", {}), J("spoken_overrides.json", {})
takes, picks = J("takes.json", {}), J("picks.json", {})
segov = J("seg_overrides.json", {})
aliases = (J("dupes.json", {}).get("aliases") or {})
official = set(J("official_keys.json", []))
fmt = gcfg.get("textFormat") or "quotes"
pad = gcfg.get("lineKeyPad")
pad = 4 if pad is None else int(pad)

# Some packs keep the narrator as a top-level object rather than a cast entry (the Shadowrun
# extractors do), so a plain characters[] lookup cannot see them at all - and the narrator is the
# single largest speaking part in the game. Normalise the same way lab/dupes.py and the server do.
cast = list(chars.get("characters") or [])
_n = chars.get("narrator")
if isinstance(_n, dict) and not any(c.get("id") == "narrator" for c in cast):
    cast.insert(0, {"id": "narrator", "name": _n.get("name") or "Narrator (GM)",
                    "lines": _n.get("lines") or []})
by_id = {c["id"]: c for c in cast}
jobs = []
for cid in a.chars.split(","):
    c = by_id.get(cid)
    if not c:
        print(f"  WARN: no character '{cid}'", file=sys.stderr)
        continue
    alias, done = aliases.get(cid) or {}, takes.get(cid) or {}
    for line in c.get("lines") or []:
        key = spoken.line_key(line, pad)
        if line.get("locked") or key.split("~")[0] in official:
            continue
        for bucket, sk, raw in spoken.segments_for(cid, key, line, segs, fmt, spoken_ov):
            if bucket != cid:                       # narrator segments belong to the narrator
                continue
            if only is not None and sk not in only:
                continue
            if alias.get(sk) or (not a.redo and (done.get(sk) or {}).get("takes")):
                continue
            text = spoken.effective_text(sk, raw, edits, directed)
            if not text.strip():
                continue
            voice = ({"voiceId": a.voice, "voiceName": a.voice_name or a.voice}
                     if a.voice else segov.get(sk) or picks.get(cid))
            if not voice:
                print(f"  WARN: {cid} has no voice — skipped", file=sys.stderr)
                break
            jobs.append({"charId": cid, "lineKey": sk, "text": text,
                         "voiceId": voice["voiceId"], "voiceName": voice.get("voiceName")})
if a.limit:
    jobs = jobs[:a.limit]

est = sum(credits(len(j["text"])) for j in jobs)
print(f"{len(jobs)} segments, {sum(len(j['text']) for j in jobs):,} chars, ~{est:,} credits")
if a.dry_run or not jobs:
    sys.exit(0)

q = queue.Queue()
for j in jobs:
    q.put(j)
lock = threading.Lock()
state = {"ok": 0, "fail": 0, "spent": 0}
t0 = time.time()
failures = []

def post(job):
    body = json.dumps({**job, "game": a.game, "stability": 0}).encode()
    req = urllib.request.Request(f"{LAB}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())

throttled_until = [0.0]                 # shared: one worker hitting the cap pauses all of them

def is_throttle(msg):
    m = (msg or "").lower()
    return "too many" in m or "rate limit" in m or "-32000" in m

def worker():
    while True:
        try:
            job = q.get_nowait()
        except queue.Empty:
            return
        err = None
        # Up to ~8 attempts, because the provider's hourly tool-call cap is a WAIT, not a failure.
        # Marking a throttled job failed and moving on drains the queue in minutes and generates
        # nothing; the first version of this did exactly that to 1,900 lines.
        for attempt in range(8):
            nap = throttled_until[0] - time.time()
            if nap > 0:
                time.sleep(min(nap, 90))
            try:
                res = post(job)
                if res.get("error"):
                    err = res["error"]
                    if is_throttle(err):
                        with lock:
                            throttled_until[0] = max(throttled_until[0],
                                                     time.time() + min(20 * (attempt + 1), 120))
                        continue
                    break                # a real error: retry once more, then give up
                err = None
                break
            except Exception as e:
                err = str(e)
                time.sleep(2 * (attempt + 1))
        with lock:
            if err:
                state["fail"] += 1
                failures.append((job["charId"], job["lineKey"], err[:120]))
            else:
                state["ok"] += 1
                state["spent"] += credits(len(job["text"]))
            n = state["ok"] + state["fail"]
            if n % 25 == 0 or n == len(jobs):
                el = time.time() - t0
                rate = n / el if el else 0
                left = (len(jobs) - n) / rate if rate else 0
                print(f"  {n}/{len(jobs)}  ok={state['ok']} fail={state['fail']} "
                      f"~{state['spent']:,} credits  {rate:.2f}/s  eta {left/60:.0f} min", flush=True)
        q.task_done()

ts = [threading.Thread(target=worker, daemon=True) for _ in range(a.workers)]
[t.start() for t in ts]
[t.join() for t in ts]
print(f"\ndone in {(time.time()-t0)/60:.1f} min: {state['ok']} generated, {state['fail']} failed, "
      f"~{state['spent']:,} credits spent")
if failures:
    print("failures (re-run this command to retry them):")
    for c, k, e in failures[:25]:
        print(f"   {c}/{k}: {e}")
