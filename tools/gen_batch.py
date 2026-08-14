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
import argparse, hashlib, json, math, os, queue, random, re, sys, threading, time, urllib.error, urllib.request

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
# A recast is not the same request as --redo. "Has a take" is true for every line of a character
# who was just recast, because the takes are all in the voice that was replaced, so a plain run
# reports the character finished and generates nothing; --redo would work but also re-buys the
# lines already remade in the new voice. This asks the only question that matters after a recast:
# is there a take in the voice this bucket is cast with NOW? Same flag, same meaning, as
# build_gen_manifest.py --recast.
ap.add_argument("--recast", action="store_true",
                help="regenerate lines that have no take in the bucket's CURRENT voice, and make "
                     "the new take the keeper")
ap.add_argument("--keys", help="comma-separated segment keys to restrict to")
ap.add_argument("--pace", type=float, default=0.0,
                help="minimum seconds between request starts, across all workers. The provider's "
                     "cap replenishes in a lump; bursting drains it in minutes and then everything "
                     "waits. Pacing just under the ceiling keeps it flowing instead.")
ap.add_argument("--stall-minutes", type=float, default=45.0,
                help="give up if nothing at all succeeds for this long")
a = ap.parse_args()
only = set(a.keys.split(",")) if a.keys else None

def already_voiced(entry, voice=None):
    """Is this key done, for the purposes of THIS run?"""
    ts = (entry or {}).get("takes") or []
    if a.redo or not ts:
        return False
    if a.recast and voice and voice.get("voiceId"):
        return any(str(t.get("voiceId")) == str(voice["voiceId"]) for t in ts)
    return True


def text_hash(text):
    """The server's hash of the words a take says (lab/server.py text_hash)."""
    return hashlib.sha1(re.sub(r"\s+", " ", text or "").strip().encode()).hexdigest()[:10]


promotions = []

def needs_promoting(charId, key, entry, voice, text):
    """A recast key that HAS a take in the new voice, but is not playing it.

    already_voiced() calls such a key done, which is right - there is nothing to buy. But the
    pack ships the KEEPER, so if the keeper is still the replaced voice the recast is inaudible
    on that line, and nothing reports it: the line looks generated and the run looks complete.
    That happens whenever the voice was auditioned on a line before the cast was changed, which
    is the normal way of choosing one. Promote the existing take instead of buying a duplicate,
    and only when it says the CURRENT words - otherwise selecting it would ship stale audio, and
    the line is better off being regenerated.
    """
    if not a.recast or not voice or not voice.get("voiceId"):
        return
    ts = (entry or {}).get("takes") or []
    sel = (entry or {}).get("selected")
    cur = next((t for t in ts if t["file"] == sel), None)
    if cur and str(cur.get("voiceId")) == str(voice["voiceId"]):
        return
    want = text_hash(text)
    match = [t for t in ts
             if str(t.get("voiceId")) == str(voice["voiceId"]) and t.get("textHash") == want]
    if match:
        promotions.append({"charId": charId, "lineKey": key, "file": match[-1]["file"]})

gcfg = json.load(open(os.path.join(ROOT, "games", a.game, "game.json")))
DATA = os.path.normpath(os.path.join(ROOT, "games", a.game, gcfg.get("dataDir") or "data"))
J = lambda n, d: json.load(open(os.path.join(DATA, n))) if os.path.exists(os.path.join(DATA, n)) else d

chars = J("characters.json", {"characters": []})
segs, edits = J("line_segments.json", {}), J("text_edits.json", {})
directed, spoken_ov = J("directed.json", {}), J("spoken_overrides.json", {})
takes, picks = J("takes.json", {}), J("picks.json", {})
segov = J("seg_overrides.json", {})
variants_doc = J("variants.json", {}).get("segments") or {}
bark_picks = J("bark_picks.json", {})
bark_over = J("bark_overrides.json", {})
char_by_name = {c["name"]: c["id"] for c in (chars.get("characters") or [])}
aliases = (J("dupes.json", {}).get("aliases") or {})
official = set(J("official_keys.json", []))
fmt = gcfg.get("textFormat") or "quotes"
pad = gcfg.get("lineKeyPad")
pad = 4 if pad is None else int(pad)

# Barks are not lines: load screens, epilogues and screen text live in barks.json under a speaker
# NAME, are split into beats by the lab (bark_segments.json), and are stored in the "_barks" take
# bucket. Nothing about the cast walk below can see them, which is how 83 load-screen beats and
# the entire 24-beat epilogue sat unvoiced while the narrator was reported as finished. Ask for
# them with the pseudo-id "_barks:<Speaker Name>", e.g. _barks:Narrator.
BARK_PREFIX = "_barks:"

def bark_jobs(speaker_query):
    barks = J("barks.json", {})
    doc = J("bark_segments.json", {})
    beats, aliases = doc.get("beats") or {}, doc.get("aliases") or {}
    bt = takes.get("_barks") or {}
    want = speaker_query.lower()
    out = []
    for key, b in barks.items():
        sp_name = (b.get("speaker") or "")
        if b.get("nonverbal") or not sp_name.lower().startswith(want):
            continue
        keys = [f"{key}~g{i}" for i in range(len(beats[key]))] if key in beats else [key]
        texts = beats.get(key) or [b.get("text") or ""]
        for sk, raw in zip(keys, texts):
            # --keys was only ever applied to the cast walk, so a bark run silently ignored it and
            # queued EVERY unvoiced bark of that speaker. Asking for 13 Hong Kong museum tags would
            # have bought 220 segments / ~72k credits instead. Honour it here too.
            if only is not None and sk not in only:
                continue
            if aliases.get(sk):                      # the same words voiced under another key
                continue
            text = edits.get(sk) if edits.get(sk) is not None else raw
            text = re.sub(r"\s+", " ", text or "").strip()
            if not text or not re.search(r"[^\W_]", re.sub(r"\[[^\]]*\]", "", text)):
                continue
            # Same rule the inspect walk below applies, and it was missing here: a bark still
            # holding a template variable would be generated with the token IN it, i.e. a voice
            # reading "Ancient Vase: yen dollar-paren-scene-dot-Museum underscore Value..." aloud.
            # Hong Kong's museum price tags are thirteen of these, and their values are runtime
            # ints with no closed set, so there is nothing to substitute - silence is the only
            # correct output until someone writes a spoken form in text_edits.json.
            if re.search(r"\$\+*\(", text):
                print(f"  SKIP {sk}: unresolved variable — {text[:60]}", file=sys.stderr)
                continue
            # bark_overrides.json is the per-BARK voice, which is how one speaker's barks can be
            # split - the MKVI's system messages are a machine and its reactions are Blitz. It was
            # not consulted here at all, so every bark took the speaker's voice regardless.
            voice = (({"voiceId": a.voice, "voiceName": a.voice_name or a.voice} if a.voice else None)
                     or bark_over.get(key) or bark_over.get(sk) or segov.get(sk)
                     or bark_picks.get(sp_name)
                     # A bark speaker is a NAME; when a character of that name exists, the bark is
                     # that character talking and belongs in their voice. Without this the fallback
                     # was the narrator, so Blitz's combat barks would have been read by Matt.
                     or picks.get(char_by_name.get(sp_name, ""))
                     or picks.get("narrator"))
            if not voice:
                print(f"  WARN: no voice for bark speaker '{sp_name}'", file=sys.stderr)
                break
            # after the voice, not before it: whether this bark still needs generating depends on
            # which voice it was made in once --recast is in play
            if already_voiced(bt.get(sk), voice):
                continue
            out.append({"charId": "_barks", "lineKey": sk, "text": text,
                        "voiceId": voice["voiceId"], "voiceName": voice.get("voiceName")})
    return out

# Inspect one-liners are a third surface, alongside dialogue and barks: the floating GM text the
# game shows when you examine a prop. They live in inspect.json keyed insp_<md5 of the raw
# inspectText>, are stored in the narrator's take bucket, and the plugin hashes the runtime string
# to find them. Nothing generated them - the lab has no inspect page and this driver had no path -
# so all 74 of Dragonfall's sat silent while every audit called the game fully voiced, because an
# audit that walks characters[] cannot see a surface that is not in characters[].
INSPECT_ID = "_inspect"
# The engine's own help-screen tutorials (tutorials.json, keyed tut_<md5>). A fourth surface, and
# the last one nothing could reach: they are not scene data, so no extractor saw them.
TUTORIAL_ID = "_tutorial"

def tutorial_jobs():
    tut = J("tutorials.json", {})
    done = takes.get("narrator") or {}
    voice = bark_picks.get("Tutorial") or picks.get("narrator")
    out = []
    for key, entry in tut.items():
        if entry.get("nonverbal"):
            continue
        if already_voiced(done.get(key), voice):
            continue
        text = spoken.effective_text(key, entry.get("text") or "", edits, directed)
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text or not re.search(r"[^\W_]", re.sub(r"\[[^\]]*\]", "", text), re.UNICODE):
            continue
        v = ({"voiceId": a.voice, "voiceName": a.voice_name or a.voice} if a.voice
             else segov.get(key) or voice)
        if not v:
            print("  WARN: no voice for tutorials", file=sys.stderr); break
        out.append({"charId": "narrator", "lineKey": key, "text": text,
                    "voiceId": v["voiceId"], "voiceName": v.get("voiceName")})
    return out


def inspect_jobs():
    insp = J("inspect.json", {})
    done = takes.get("narrator") or {}
    voice = picks.get("narrator")
    out = []
    for key, entry in insp.items():
        # the voice first: after a recast, whether a key still needs generating depends on it
        v = ({"voiceId": a.voice, "voiceName": a.voice_name or a.voice} if a.voice
             else segov.get(key) or voice)
        if already_voiced(done.get(key), v):
            continue
        raw = entry.get("spoken") if isinstance(entry, dict) else entry
        text = spoken.effective_text(key, raw, edits, directed)
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text or not re.search(r"[^\W_]", re.sub(r"\[[^\]]*\]", "", text), re.UNICODE):
            continue
        # A template variable here is not a name we can resolve: scene.CafeSpecial is re-set eight
        # times as you play (caramel soykaf, apple pie chai, Wyrm-Rock energy cola...). One clip
        # cannot be right for all of them, and speaking the wrong drink over the on-screen text is
        # worse than silence, so leave it unvoiced rather than guess.
        if re.search(r"\$\+*\(", text):
            if not (variants_doc.get(key) or {}).get("v"):
                print(f"  SKIP {key}: unresolved variable — {text[:60]}", file=sys.stderr)
                continue
            # It has a closed value set, so the variants below carry the real words and the
            # generic take is skipped rather than reading the token aloud.
            for vid, vtext in variants_doc[key]["v"].items():
                vk = f"{key}#{vid}"
                vv = v
                if already_voiced(done.get(vk), vv):
                    continue
                out.append({"charId": "narrator", "lineKey": vk,
                            "text": re.sub(r"\s+", " ", vtext).strip(),
                            "voiceId": vv["voiceId"], "voiceName": vv.get("voiceName")})
            continue
        if not v:
            print("  WARN: no narrator voice for inspect lines", file=sys.stderr); break
        out.append({"charId": "narrator", "lineKey": key, "text": text,
                    "voiceId": v["voiceId"], "voiceName": v.get("voiceName")})
        for vid, vtext in (variants_doc.get(key, {}).get("v") or {}).items():
            vk = f"{key}#{vid}"
            if already_voiced(done.get(vk), v):
                continue
            vtext = re.sub(r"\s+", " ", vtext or "").strip()
            if vtext and vtext != text:
                out.append({"charId": "narrator", "lineKey": vk, "text": vtext,
                            "voiceId": v["voiceId"], "voiceName": v.get("voiceName")})
    return out

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
wanted = [x for x in a.chars.split(",")
          if not x.startswith(BARK_PREFIX) and x not in (INSPECT_ID, TUTORIAL_ID)]
for spec in a.chars.split(","):
    if spec.startswith(BARK_PREFIX):
        jobs += bark_jobs(spec[len(BARK_PREFIX):])
    elif spec == INSPECT_ID:
        jobs += inspect_jobs()
    elif spec == TUTORIAL_ID:
        jobs += tutorial_jobs()
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
            if alias.get(sk):
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
            # A segment can need its variants even when its generic take is already made, so the
            # "already voiced" test is applied per KEY rather than skipping the segment outright.
            if not already_voiced(done.get(sk), voice):
                jobs.append({"charId": cid, "lineKey": sk, "text": text,
                             "voiceId": voice["voiceId"], "voiceName": voice.get("voiceName")})
            else:
                needs_promoting(cid, sk, done.get(sk), voice, text)
            # Template-variable variants: the same segment said once per value the game can
            # substitute (five metatypes, two genders...). Keyed "<segKey>#<variantId>"; the pack
            # ships them alongside the generic take and the plugin falls back to the generic when
            # a variant was never generated.
            for vid, vtext in (variants_doc.get(sk, {}).get("v") or {}).items():
                vk = f"{sk}#{vid}"
                if alias.get(vk) or already_voiced(done.get(vk), voice):
                    continue
                vtext = re.sub(r"\s+", " ", vtext or "").strip()
                if not vtext or vtext == text:
                    continue
                jobs.append({"charId": cid, "lineKey": vk, "text": vtext,
                             "voiceId": voice["voiceId"], "voiceName": voice.get("voiceName")})
if os.environ.get("GEN_BREAKDOWN"):
    v=[j for j in jobs if "#" in j["lineKey"]]
    print(f"  breakdown: {len(jobs)-len(v)} generic, {len(v)} variant clips", file=sys.stderr)
if a.limit:
    jobs = jobs[:a.limit]

est = sum(credits(len(j["text"]), j["voiceId"]) for j in jobs)
print(f"{len(jobs)} segments, {sum(len(j['text']) for j in jobs):,} chars, ~{est:,} credits"
      + (f", {len(promotions)} already voiced but not selected" if promotions else ""))
if a.dry_run:
    for p in promotions:
        print(f"  would promote {p['charId']} {p['lineKey']} -> {os.path.basename(p['file'])}")
    sys.exit(0)

# Costs nothing and must happen even when there is nothing to generate: these lines are the ones
# that look finished and are not.
for p in promotions:
    try:
        req = urllib.request.Request(f"{LAB}/api/take/select",
                                     data=json.dumps({**p, "game": a.game}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
        print(f"  promoted {p['charId']} {p['lineKey']} -> {os.path.basename(p['file'])}")
    except Exception as e:
        print(f"  WARN: could not promote {p['lineKey']}: {e}", file=sys.stderr)
if not jobs:
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
                if res.get("ok") and (a.redo or a.recast) and not a.voice and res.get("file"):
                    # A retake does not become the keeper on its own: /api/generate only fills
                    # `selected` when it was empty, so that auditioning in the lab never silently
                    # replaces a chosen take. But --redo exists precisely because the current
                    # keeper is wrong - it was made from a script that has since changed - so
                    # leaving it selected reships the audio this run was meant to replace. That
                    # happened three times before this line existed. --recast is the same story
                    # with a different cause: the keeper is in the voice that was just replaced,
                    # and a recast nobody can hear is not a recast.
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
