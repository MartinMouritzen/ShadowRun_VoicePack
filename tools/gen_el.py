#!/usr/bin/env python3
"""Generate the ElevenLabs jobs (account voices) up to a monthly-quota budget, in priority order.
Writes audio to app/audio/<charId>/takes/ and results to tools/gen/el_results.jsonl (one JSON/line).
Does NOT touch takes.json (avoids races with the Magnific workers); merge_takes.py does that.
Priority: non-narrator characters first (always fit), then narrator dialogue, then inspect one-liners.
Deferred jobs (over budget) are written to tools/gen/el_deferred.json."""
import json, os, time, urllib.request, urllib.error

ROOT = os.path.join(os.path.dirname(__file__), "..")
KEY = open(os.path.join(ROOT, ".elevenlabs.key")).read().strip()
BUDGET = 84000   # leave a safety margin under the 90k monthly limit (minus already-used)

jobs = json.load(open(os.path.join(ROOT, "tools/gen/el_jobs.json")))

# live remaining quota
def remaining():
    req = urllib.request.Request("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": KEY})
    s = json.load(urllib.request.urlopen(req, timeout=30))["subscription"]
    return s["character_limit"] - s["character_count"]

budget = min(BUDGET, remaining() - 500)

def prio(j):
    if j["charId"] != "narrator": return 0
    if j["segKey"].startswith("insp_"): return 2
    return 1
jobs.sort(key=prio)

out = open(os.path.join(ROOT, "tools/gen/el_results.jsonl"), "a")
deferred = []
spent = 0; ok = err = 0
for j in jobs:
    n = len(j["text"])
    if spent + n > budget:
        deferred.append(j); continue
    fn_dir = os.path.join(ROOT, "app", "audio", j["charId"], "takes")
    os.makedirs(fn_dir, exist_ok=True)
    body = json.dumps({"text": j["text"], "model_id": "eleven_v3",
                       "voice_settings": {"stability": 0, "use_speaker_boost": True}}).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{j['voiceId']}?output_format=mp3_44100_128",
        data=body, method="POST", headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    try:
        audio = urllib.request.urlopen(req, timeout=120).read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:120]
        if e.code == 401 or "quota" in msg.lower():
            print(f"QUOTA HIT at {spent} chars — deferring rest"); deferred.append(j)
            deferred.extend(jobs[jobs.index(j)+1:]); break
        print(f"FAIL {j['segKey']}: {e.code} {msg}"); err += 1; continue
    ts = int(time.time())
    fname = f"{j['segKey']}__{j['voiceId'][:12]}__{ts}.mp3"
    open(os.path.join(fn_dir, fname), "wb").write(audio)
    rel = f"{j['charId']}/takes/{fname}"
    out.write(json.dumps({"charId": j["charId"], "segKey": j["segKey"], "file": rel,
                          "voiceId": j["voiceId"], "voiceName": j["voiceName"],
                          "stability": 0, "chars": n, "ts": ts}) + "\n")
    out.flush()
    spent += n; ok += 1
    if ok % 25 == 0: print(f"  {ok} done, {spent} chars")
    time.sleep(0.25)
out.close()
json.dump(deferred, open(os.path.join(ROOT, "tools/gen/el_deferred.json"), "w"), ensure_ascii=False)
print(f"EL DONE: {ok} generated ({spent} chars), {err} errors, {len(deferred)} deferred (over quota)")
