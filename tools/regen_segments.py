#!/usr/bin/env python3
"""Regenerate named segments in their owning character's picked voice.

Usage: regen_segments.py <game> <charId>:<segKey> [...]   [--dry] [--stability N]
       regen_segments.py <game> --from-audit          (regenerate every keeper audit_takes.py flags)

Mirrors the lab exactly so a regenerated take is indistinguishable from one made by clicking
Generate: text precedence is text_edits -> directed.json -> spoken_overrides -> the line text with
{{GM}} narration stripped (lab.html effText + ttsText), the voice is seg_overrides[segKey] or the
character's pick, and the take record matches server.py's /api/generate. The new take becomes the
keeper; the old one is kept so it can still be compared in the lab.

Pairs with audit_takes.py: that finds takes whose audio does not fit their text, this replaces them.
"""
import json, os, re, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
args = sys.argv[1:]
GAME = next((a for a in args if not a.startswith("-") and ":" not in a), None)
if GAME not in ("dms", "dragonfall", "hk"): sys.exit("usage: regen_segments.py <game> <charId>:<segKey> ...")
DRY = "--dry" in args
STAB = float(args[args.index("--stability") + 1]) if "--stability" in args else 0.0
pairs = [a.split(":", 1) for a in args if ":" in a and not a.startswith("-")]

sys.path.insert(0, os.path.join(ROOT, "app"))
os.chdir(os.path.join(ROOT, "app"))          # server.py resolves its key/token files relative to app/
import server                                # noqa: E402

D = os.path.join(ROOT, "app", "data", GAME); AUDIO = os.path.join(ROOT, "app", "audio", GAME)
def J(n, d=None):
    p = os.path.join(D, n)
    return json.load(open(p)) if os.path.exists(p) else d
chars = J("characters.json"); SEGS = J("line_segments.json", {}); SPOKEN = J("spoken_overrides.json", {})
EDITS = J("text_edits.json", {}); DIRECTED = J("directed.json", {}); SEGOV = J("seg_overrides.json", {})
picks = J("picks.json", {})
byid = {c["id"]: c for c in chars["characters"]}
byid["narrator"] = dict(chars["narrator"], id="narrator")

if "--from-audit" in args:
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "audit_takes.py"), GAME, "--json"],
                         capture_output=True, text=True).stdout
    pairs = [[f["bucket"], f["seg"]] for f in json.loads(out) if f["keeper"]]
    print(f"audit flagged {len(pairs)} keeper(s)")

def tts_text(cid, l):
    o = SPOKEN.get(f'{l["c"]}_{l["n"]}')
    if o: return o["spoken"]
    t = l["t"]
    if cid != "narrator": t = re.sub(r'\{\{GM\}\}[\s\S]*?(\{\{/GM\}\}|$)', ' ', t)
    return re.sub(r'\s+', ' ', re.sub(r'\{\{/?[A-Za-z]*\}\}', '', t)).strip()

BARKS = J("barks.json", {})
BARK_OV = J("bark_overrides.json", {})

BARK_SEGS = (J("bark_segments.json", {}) or {}).get("beats") or {}

def text_for(cid, seg_key):
    """The exact string the lab would submit for this segment key."""
    bark_base = seg_key.split("~")[0]
    if bark_base in BARKS:          # barks live in their own store, not in characters.json
        # A hand edit still wins here, exactly as it does in the lab (genBark sends the edited
        # script). bark_overrides.json is a VOICE map, not a text one — reading it here used to
        # hand the TTS a {"voiceId": ...} dict for any bark with a per-line voice.
        if EDITS.get(seg_key) is not None: return EDITS[seg_key]
        if seg_key != bark_base:    # one beat of a long piece of narration
            beats = BARK_SEGS.get(bark_base) or []
            i = int(seg_key[len(bark_base) + 2:] or 0)
            return beats[i] if i < len(beats) else None
        return BARKS[bark_base]["text"]
    base = seg_key.split("~")[0]
    tail = seg_key[len(base):]
    if EDITS.get(seg_key) is not None: return EDITS[seg_key]
    if DIRECTED.get(seg_key) is not None: return DIRECTED[seg_key]
    if tail:                                          # a slice of a hand-segmented line
        raw = SEGS.get(base) or []
        want, idx = tail[1], int(tail[2:] or 0)
        seen = -1
        for s in raw:
            if (s["who"] == "gm") == (want == "g"):
                seen += 1
                if seen == idx: return s["t"]
        return None
    for c in byid.values():
        for l in c.get("lines", []):
            if f'{l["c"]}_{l["n"]}' == base: return tts_text(cid, l)
    return None

takes = json.load(open(os.path.join(D, "takes.json")))
jobs = []
for cid, seg_key in pairs:
    if cid not in byid and cid not in takes: sys.exit(f"ERROR: unknown bucket '{cid}'")
    t = text_for(cid, seg_key)
    if not t: sys.exit(f"ERROR: no text for {cid}:{seg_key}")
    bark_base = seg_key.split("~")[0]
    if bark_base in BARKS:          # bark voices are cast per SPEAKER NAME, not per bucket
        pick = (BARK_OV.get(bark_base)
                or J("bark_picks.json", {}).get(BARKS[bark_base]["speaker"]))
    else:
        pick = SEGOV.get(seg_key) or picks.get(cid)
    if not pick:      # mixed bucket with no character pick: reuse whatever voice made the last take
        e = takes.get(cid, {}).get(seg_key) or {}
        prev = next((x for x in e.get("takes", []) if x["file"] == e.get("selected")), None)
        if prev: pick = {"voiceId": prev["voiceId"], "voiceName": prev["voiceName"]}
    if not pick: sys.exit(f"ERROR: no voice for {cid}:{seg_key}")
    jobs.append({"cid": cid, "key": seg_key, "text": t, **pick})

if DRY:
    for j in jobs: print(f"  {j['cid']:<26} {j['key']:<36} {len(j['text']):>4}ch {j['voiceName']}\n"
                         f"      {j['text'][:110]!r}")
    print(f"{len(jobs)} segment(s), {sum(len(j['text']) for j in jobs)} chars"); sys.exit(0)

done = fail = 0
for i, j in enumerate(jobs, 1):
    vid = str(j["voiceId"])
    try:
        if vid.startswith("mag_"):
            audio = server.magnific_generate(j["text"], int(vid[4:]), STAB); tag = "mag" + vid[4:]
        else:
            server.ensure_voice(vid); tag = vid[:12]
            audio = server.el_request(f"/v1/text-to-speech/{vid}?output_format=mp3_44100_128",
                                      method="POST", raw=True,
                                      body={"text": j["text"], "model_id": "eleven_v3",
                                            "voice_settings": {"stability": STAB, "use_speaker_boost": True}})
    except Exception as e:
        print(f"  [{i}/{len(jobs)}] FAILED {j['cid']}:{j['key']}: {e}"); fail += 1; continue
    ts = int(time.time())
    d = os.path.join(AUDIO, j["cid"], "takes"); os.makedirs(d, exist_ok=True)
    fname = f"{j['key']}__{tag}__{ts}.mp3"
    open(os.path.join(d, fname), "wb").write(audio)
    rel = f"{j['cid']}/takes/{fname}"
    arr = takes.setdefault(j["cid"], {}).setdefault(j["key"], {"selected": None, "takes": []})
    arr["takes"].append({"file": rel, "voiceId": j["voiceId"], "voiceName": j["voiceName"],
                         "stability": STAB, "chars": len(j["text"]), "ts": ts})
    arr["selected"] = rel
    json.dump(takes, open(os.path.join(D, "takes.json"), "w"), ensure_ascii=False, indent=1)
    done += 1
    print(f"  [{i}/{len(jobs)}] {j['cid']:<26} {j['key']:<36} {len(j['text']):>4}ch  {j['voiceName']}")
print(f"regenerated {done} segment(s), {fail} failure(s)")
sys.exit(1 if fail else 0)
