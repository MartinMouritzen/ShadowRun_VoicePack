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
import argparse, json, math, os, queue, random, re, sys, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))     # ~/dev/voices
sys.path.insert(0, os.path.join(ROOT, "lab"))
import spoken                                                      # noqa: E402

LAB = os.environ.get("LAB_URL", "http://localhost:3719")
def credits(n, voice_id=""):
    """Magnific's price for n characters — verified against simulate_cost at eight lengths.
    Locally synthesised voices cost nothing, and reporting them as spend makes the run's own
    accounting a lie."""
    if str(voice_id).startswith("sapi_"):
        return 0
    if not str(voice_id).startswith("mag_"):
        return n          # ElevenLabs bills one credit per character, and it is a much smaller pot
    return 2 * math.ceil(math.ceil(n / 5) / 2)

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
ap.add_argument("--pace", type=float, default=0.0,
                help="minimum seconds between request starts, across all workers. The provider's "
                     "cap replenishes in a lump; bursting drains it in minutes and then everything "
                     "waits. Pacing just under the ceiling keeps it flowing instead.")
ap.add_argument("--stall-minutes", type=float, default=45.0,
                help="give up if nothing at all succeeds for this long")
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
wanted = a.chars.split(",")
for cid in wanted:
    if cid not in by_id:
        print(f"  WARN: no character '{cid}'", file=sys.stderr)
# A take store bucket is not the same thing as the character who owns the line. Narration is the
# case that matters: {{GM}} segments inside anyone's dialogue belong to the 'narrator' bucket, and
# in Dragonfall that is three quarters of everything the narrator says. Walking only the requested
# character's own lines made all of it unreachable - the same shape of bug as the narrator not
# being in characters[] at all. So scan every line and keep the segments whose BUCKET was asked for.
for owner in cast:
    ocid = owner.get("id")
    for line in owner.get("lines") or []:
        key = spoken.line_key(line, pad)
        if line.get("locked") or key.split("~")[0] in official:
            continue
        for bucket, sk, raw in spoken.segments_for(ocid, key, line, segs, fmt, spoken_ov):
            if bucket not in wanted:
                continue
            cid = bucket
            alias, done = aliases.get(cid) or {}, takes.get(cid) or {}
            if only is not None and sk not in only:
                continue
            if alias.get(sk) or (not a.redo and (done.get(sk) or {}).get("takes")):
                continue
            text = spoken.effective_text(sk, raw, edits, directed)
            if not text.strip():
                continue
            # Nothing to say: the segment is punctuation or bare markup like '>><<', which the
            # extractor keeps because it is part of the on-screen text. Direction tags are not
            # spoken either, so a segment with no letters or digits outside them yields silence -
            # SAPI returns an empty wav and a neural voice bills for a shrug. Seven of these exist
            # in Dragonfall and each was a hard failure that no number of retries could clear.
            if not re.search(r"[^\W_]", re.sub(r"\[[^\]]*\]", "", text), re.UNICODE):
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

est = sum(credits(len(j["text"]), j["voiceId"]) for j in jobs)
print(f"{len(jobs)} segments, {sum(len(j['text']) for j in jobs):,} chars, ~{est:,} credits")
if a.dry_run or not jobs:
    sys.exit(0)

q = queue.Queue()
for j in jobs:
    q.put(j)
lock = threading.Lock()
state = {"ok": 0, "fail": 0, "spent": 0, "throttled": 0}
t0 = time.time()
failures = []

def post(job):
    body = json.dumps({**job, "game": a.game, "stability": 0}).encode()
    req = urllib.request.Request(f"{LAB}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # The server answers a refused generation with 502 AND a JSON body saying why. urlopen
        # raises before that body is read, so every such line was reported as a bare
        # "HTTP Error 502: Bad Gateway" - which is exactly the message the server was changed to
        # stop giving. Read the body and hand back the real reason.
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": f"HTTP {e.code}"}

throttled_until = [0.0]                 # shared: one worker hitting the cap pauses all of them
next_start = [0.0]                      # shared: proactive pacing, see --pace
last_success = [time.time()]
pace_lock = threading.Lock()

def is_throttle(msg):
    m = (msg or "").lower()
    return "too many" in m or "rate limit" in m or "-32000" in m

def take_slot():
    """Space request starts out across all workers."""
    if a.pace <= 0:
        return
    while True:
        with pace_lock:
            now = time.time()
            if now >= next_start[0]:
                next_start[0] = max(now, next_start[0]) + a.pace
                return
            wait = next_start[0] - now
        time.sleep(min(wait, 5))

def worker():
    while True:
        try:
            job = q.get_nowait()
        except queue.Empty:
            return
        err = None
        # A throttle is never a failed line and never costs the job an attempt: it goes back on
        # the queue and something else is tried meanwhile. Only genuine errors are retried a fixed
        # number of times and then given up on. An earlier version spent its attempts sleeping
        # through a closed quota and then marked the line failed, which lost 1,900 of them.
        for attempt in range(3):
            nap = throttled_until[0] - time.time()
            if nap > 0:
                time.sleep(min(nap, 30) + random.uniform(0, 3))   # jitter: avoid a thundering herd
            take_slot()
            try:
                res = post(job)
                # --voice means this is an AUDITION: several candidates on one line, compared in
                # the lab. The keeper is the user's decision there, so forcing it here would mean
                # whichever candidate ran last silently became the shipped take.
                if res.get("ok") and a.redo and not a.voice and res.get("file"):
                    # A retake does not become the keeper on its own: /api/generate only fills
                    # `selected` when it was empty, so that auditioning in the lab never silently
                    # replaces a chosen take. But --redo exists precisely because the current
                    # keeper is wrong - it was made from a script that has since changed - so
                    # leaving it selected reships the audio this run was meant to replace. That
                    # happened three times before this line existed.
                    try:
                        sel = json.dumps({"game": a.game, "charId": job["charId"],
                                          "lineKey": job["lineKey"], "file": res["file"]}).encode()
                        urllib.request.urlopen(urllib.request.Request(
                            f"{LAB}/api/take/select", data=sel,
                            headers={"Content-Type": "application/json"}), timeout=60).read()
                    except Exception as e:
                        print(f"  WARN: generated but could not select {job['lineKey']}: {e}",
                              file=sys.stderr)
                if res.get("error"):
                    err = res["error"]
                    if is_throttle(err):
                        with lock:
                            throttled_until[0] = max(throttled_until[0], time.time() + 30)
                            state["throttled"] += 1
                        q.put(job)                # try it again later, behind the rest
                        err = "__requeued__"
                        break
                    continue                      # a real error: retry
                err = None
                break
            except Exception as e:
                err = str(e)
                time.sleep(2 * (attempt + 1))
        with lock:
            if err == "__requeued__":
                pass
            elif err:
                state["fail"] += 1
                failures.append((job["charId"], job["lineKey"], err[:120]))
            else:
                state["ok"] += 1
                state["spent"] += credits(len(job["text"]), job["voiceId"])
                last_success[0] = time.time()
            if time.time() - last_success[0] > a.stall_minutes * 60:
                print(f"  STOPPING: nothing has succeeded for {a.stall_minutes:.0f} min — "
                      f"the quota looks closed. Re-run later to resume.", flush=True)
                while not q.empty():
                    try: q.get_nowait()
                    except queue.Empty: break
                return
            n = state["ok"] + state["fail"]
            if n % 25 == 0 or n == len(jobs):
                el = time.time() - t0
                rate = n / el if el else 0
                left = (len(jobs) - n) / rate if rate else 0
                print(f"  {n}/{len(jobs)}  ok={state['ok']} fail={state['fail']} thr={state['throttled']} "
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
