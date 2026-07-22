using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using UnityEngine;

namespace SRRVoices
{
    // Persistent MonoBehaviour that streams OGG clips from disk (Unity 4 WWW) and plays a line's
    // segments in order (narrator clip, then character clip, etc). One AudioSource, 2D.
    public class VoicePlayer : MonoBehaviour
    {
        AudioSource src;
        readonly Dictionary<string, AudioClip> cache = new Dictionary<string, AudioClip>();
        int playToken = 0;                 // bump to cancel any in-flight sequence
        string root = "";

        // Pitch-preserving speed: clips time-stretched via WSOLA, keyed by rel path, all baked
        // at one speed (stretchedAtSpeed); a speed change flushes them. currentClipFactor is the
        // speed baked into the clip assigned to src (1 = unstretched), so the effective pitch to
        // reach the configured speed is Speed()/currentClipFactor.
        readonly Dictionary<string, AudioClip> stretched = new Dictionary<string, AudioClip>();
        float stretchedAtSpeed = 1f;
        float currentClipFactor = 1f;
        bool stretchBroken = false;        // set if clip PCM turns out to be unreadable
        bool stretchLogged = false;        // one positive log line proving the stretch path ran

        void Awake()
        {
            src = gameObject.AddComponent<AudioSource>();
            src.playOnAwake = false;
            src.loop = false;
            src.ignoreListenerPause = true;
            src.panLevel = 0f;             // Unity 4: 0 = 2D (no 3D spatialization)
            src.volume = Vol();
        }

        public void SetRoot(string r) { root = r; }

        // Shift+Plus / Shift+Minus: live playback-speed adjustment. Persists via the config entry
        // (BepInEx saves on set). A small OSD confirms the new value for a moment.
        float osdUntil = 0f;
        string osdText = "";

        void Update()
        {
            // Stretched clips that were flushed while still audible get destroyed here once
            // their source lets go of them (see FlushStretched).
            if (deferredDestroy.Count > 0) SweepDeferred();
            if (Plugin.CfgSpeed == null) return;
            bool shift = Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);
            if (!shift) return;
            float delta = 0f;
            if (Input.GetKeyDown(KeyCode.Equals) || Input.GetKeyDown(KeyCode.Plus) || Input.GetKeyDown(KeyCode.KeypadPlus)) delta = 0.05f;
            else if (Input.GetKeyDown(KeyCode.Minus) || Input.GetKeyDown(KeyCode.KeypadMinus)) delta = -0.05f;
            if (delta == 0f) return;
            float v = Mathf.Clamp(Plugin.CfgSpeed.Value + delta, 0.5f, 2f);
            v = Mathf.Round(v * 100f) / 100f;      // keep the cfg value tidy (1.05, 1.1, ...)
            Plugin.CfgSpeed.Value = v;
            ApplyLive();                                       // apply to the line playing right now
            osdText = "Voice speed: " + v.ToString("0.00") + "x";
            osdUntil = Time.realtimeSinceStartup + 2f;
            if (Plugin.Log != null) Plugin.Log.LogInfo(osdText);
        }

        static Texture2D white;   // Unity 4.2 has no Texture2D.whiteTexture

        void OnGUI()
        {
            if (Time.realtimeSinceStartup > osdUntil) return;
            if (white == null)
            {
                white = new Texture2D(1, 1);
                white.SetPixel(0, 0, Color.white);
                white.Apply();
            }
            GUIStyle st = new GUIStyle(GUI.skin.label);
            st.fontSize = 18;
            st.fontStyle = FontStyle.Bold;
            st.normal.textColor = Color.white;
            GUI.color = new Color(0f, 0f, 0f, 0.75f);
            GUI.DrawTexture(new Rect(18f, 14f, 220f, 34f), white);
            GUI.color = Color.white;
            GUI.Label(new Rect(28f, 20f, 210f, 26f), osdText, st);
        }

        static float Vol()
        {
            return (Plugin.CfgVolume != null) ? Mathf.Clamp01(Plugin.CfgVolume.Value) : 1f;
        }

        static float Speed()
        {
            return (Plugin.CfgSpeed != null) ? Mathf.Clamp(Plugin.CfgSpeed.Value, 0.5f, 2f) : 1f;
        }

        // Identifies the current playback request; used to stop loadscreen narration when the
        // loading screen closes without killing whatever line may have started since.
        public int CurrentToken() { return playToken; }

        static bool PreservePitch()
        {
            return Plugin.CfgPreservePitch == null || Plugin.CfgPreservePitch.Value;
        }

        // Re-read volume/speed config and apply to whatever is playing right now (options sliders).
        // A clip already playing keeps whatever stretch it was baked with; the residual pitch
        // covers the difference until the next line starts (which stretches at the new speed).
        public void ApplyLive()
        {
            if (src == null) return;
            src.volume = Vol();
            src.pitch = Speed() / currentClipFactor;
            if (barkSrcs != null)
                for (int i = 0; i < barkSrcs.Length; i++)
                    if (barkSrcs[i] != null)
                    {
                        barkSrcs[i].volume = Vol();
                        barkSrcs[i].pitch = Speed() / barkFactor[i];
                    }
        }

        public void StopAll()
        {
            playToken++;
            if (src != null) src.Stop();
            StopBarks();
        }

        public void PlaySequence(string[] relPaths)
        {
            playToken++;
            int myToken = playToken;
            if (src != null) src.Stop();
            StopBarks();   // dialogue/narration/inspects preempt combat barks
            StartCoroutine(PlaySeq(relPaths, myToken));
        }

        // ---- combat barks -------------------------------------------------------
        // Barks play on their own small pool of AudioSources so a new bark never truncates one
        // already playing: two actors shouting at once overlap, the same way their text bubbles
        // do on screen. Barks never preempt the main channel either; only the main channel
        // (dialogue, inspects, loadscreen narration) silences barks, via StopBarks().
        AudioSource[] barkSrcs;
        bool[] barkBusy;
        string[] barkRel;     // first clip of the bark each slot is voicing (echo suppression)
        float[] barkFactor;   // stretch factor baked into the clip each slot is playing
        int barkGen = 0;      // bump to cancel all in-flight bark sequences

        int FreeBarkSlot()
        {
            if (barkSrcs == null)
            {
                barkSrcs = new AudioSource[3];
                barkBusy = new bool[3];
                barkRel = new string[3];
                barkFactor = new float[] { 1f, 1f, 1f };
                for (int i = 0; i < barkSrcs.Length; i++)
                {
                    AudioSource s = gameObject.AddComponent<AudioSource>();
                    s.playOnAwake = false;
                    s.loop = false;
                    s.ignoreListenerPause = true;
                    s.panLevel = 0f;
                    barkSrcs[i] = s;
                }
            }
            for (int i = 0; i < barkSrcs.Length; i++)
                if (!barkBusy[i]) return i;
            return -1;
        }

        public void PlayBark(string[] relPaths)
        {
            if (relPaths == null || relPaths.Length == 0) return;
            bool log = Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value && Plugin.Log != null;
            // Bark clips are keyed by text, so a repeat of the SAME line while it's still in the
            // air would layer the identical waveform over its own tail (echo/phasing). Drop it;
            // the line is literally already being shouted.
            if (barkRel != null)
                for (int i = 0; i < barkRel.Length; i++)
                    if (barkBusy[i] && barkRel[i] == relPaths[0])
                    {
                        if (log) Plugin.Log.LogInfo("bark dropped (same line already playing)");
                        return;
                    }
            int slot = FreeBarkSlot();
            if (slot < 0)
            {
                // three actors already shouting; dropping the fourth beats cutting one off
                if (log) Plugin.Log.LogInfo("bark dropped (all bark sources busy)");
                return;
            }
            barkBusy[slot] = true;
            barkRel[slot] = relPaths[0];
            StartCoroutine(PlayBarkSeq(slot, relPaths, barkGen));
        }

        public void StopBarks()
        {
            barkGen++;
            if (barkSrcs == null) return;
            for (int i = 0; i < barkSrcs.Length; i++)
                if (barkSrcs[i] != null) barkSrcs[i].Stop();
        }

        IEnumerator PlayBarkSeq(int slot, string[] relPaths, int myGen)
        {
            try
            {
                AudioSource s = barkSrcs[slot];
                for (int i = 0; i < relPaths.Length; i++)
                {
                    if (myGen != barkGen) yield break;
                    AudioClip clip = null;
                    if (!cache.TryGetValue(relPaths[i], out clip) || clip == null)
                    {
                        string capture = relPaths[i];
                        yield return StartCoroutine(LoadClip(capture, delegate(AudioClip c) { clip = c; }));
                    }
                    if (myGen != barkGen) yield break;
                    if (clip == null) continue;
                    AudioClip toPlay = clip;
                    // token -1: reuse the stretch cache without touching currentClipFactor
                    yield return StartCoroutine(StretchAsync(relPaths[i], clip, -1,
                        delegate(AudioClip c) { toPlay = c; }));
                    if (myGen != barkGen || s == null) yield break;
                    float factor = (toPlay != clip) ? Speed() : 1f;
                    barkFactor[slot] = factor;
                    s.volume = Vol();
                    s.clip = toPlay;
                    s.pitch = Speed() / factor;
                    s.Play();
                    while (myGen == barkGen && s != null && s.isPlaying)
                        yield return null;
                    if (myGen != barkGen) yield break;
                    if (i < relPaths.Length - 1)
                    {
                        float gap = (Plugin.CfgSegmentGap != null) ? Mathf.Max(0f, Plugin.CfgSegmentGap.Value) : 0.3f;
                        float t0 = Time.realtimeSinceStartup;
                        while (myGen == barkGen && (Time.realtimeSinceStartup - t0) < gap)
                            yield return null;
                        if (myGen != barkGen) yield break;
                    }
                }
            }
            finally
            {
                barkBusy[slot] = false;
            }
        }

        IEnumerator PlaySeq(string[] relPaths, int myToken)
        {
            for (int i = 0; i < relPaths.Length; i++)
            {
                if (myToken != playToken) yield break;
                AudioClip clip = null;
                if (!cache.TryGetValue(relPaths[i], out clip) || clip == null)
                {
                    string capture = relPaths[i];
                    yield return StartCoroutine(LoadClip(capture, delegate(AudioClip c) { clip = c; }));
                }
                if (myToken != playToken) yield break;
                if (clip == null) continue;      // failed load -> skip this segment, keep going
                AudioClip toPlay = clip;
                yield return StartCoroutine(StretchAsync(relPaths[i], clip, myToken,
                    delegate(AudioClip c) { toPlay = c; }));
                if (myToken != playToken) yield break;
                src.volume = Vol();
                src.clip = toPlay;
                src.pitch = Speed() / currentClipFactor;
                src.Play();
                // Wait until this clip finishes or we get preempted (Unity 4 has no WaitWhile).
                while (myToken == playToken && src != null && src.isPlaying)
                    yield return null;
                if (myToken != playToken) yield break;
                // Natural beat between segments (narrator -> character, etc.) so the voice swap
                // doesn't feel abrupt. Not before the first clip or after the last.
                if (i < relPaths.Length - 1)
                {
                    float gap = (Plugin.CfgSegmentGap != null) ? Mathf.Max(0f, Plugin.CfgSegmentGap.Value) : 0.3f;
                    float t0 = Time.realtimeSinceStartup;
                    while (myToken == playToken && (Time.realtimeSinceStartup - t0) < gap)
                        yield return null;
                    if (myToken != playToken) yield break;
                }
            }
        }

        // ---- pitch-preserving time-stretch (WSOLA) ------------------------------
        // AudioSource.pitch alone is a tape-style speedup: 2x speed = +1 octave (Mickey Mouse).
        // Instead, when PreservePitch is on, bake the tempo change into the samples with a
        // waveform-similarity overlap-add stretch and play the result at its natural pitch.

        // Hands `done` the clip to actually play (stretched when possible, the original otherwise)
        // and sets currentClipFactor to the speed baked into it. The sample crunching runs on a
        // background thread: typical clips take a few ms, but minute-long narration would freeze
        // the main thread for a second or more on the game's old Mono runtime.
        IEnumerator StretchAsync(string rel, AudioClip clip, int token, Action<AudioClip> done)
        {
            float speed = Speed();
            if (stretchBroken || !PreservePitch() || Mathf.Abs(speed - 1f) < 0.025f)
            {
                if (stretched.Count > 0) FlushStretched();   // back to 1x / feature off: free the PCM
                if (playToken == token) currentClipFactor = 1f;
                done(clip); yield break;
            }
            if (!clip.isReadyToPlay)
            {
                // still decoding (LoadClip's ready-wait can time out on a slow disk); play it raw
                // this once rather than concluding the PCM is unreadable for the whole session
                if (playToken == token) currentClipFactor = 1f;
                done(clip); yield break;
            }
            if (Mathf.Abs(stretchedAtSpeed - speed) > 0.001f) FlushStretched();
            stretchedAtSpeed = speed;

            AudioClip hit;
            if (stretched.TryGetValue(rel, out hit) && hit != null)
            {
                if (playToken == token) currentClipFactor = speed;
                done(hit); yield break;
            }

            int channels = clip.channels;
            int freqHz = clip.frequency;
            float[] data = null;
            try
            {
                data = new float[clip.samples * channels];
                clip.GetData(data, 0);
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("preserve-pitch: GetData failed: " + e.Message);
                data = null;
            }
            if (data == null || AllZero(data))
            {
                // WWW-loaded clip refused to hand over PCM; without samples there is nothing
                // to stretch, so fall back to tape-style speed for the rest of the session.
                stretchBroken = true;
                if (Plugin.Log != null)
                    Plugin.Log.LogWarning("preserve-pitch: clip PCM not readable; falling back to tape-style speed (pitch will shift).");
                if (playToken == token) currentClipFactor = 1f;
                done(clip); yield break;
            }

            StretchJob job = new StretchJob(data, channels, freqHz, speed);
            Thread worker = new Thread(job.Run);
            worker.IsBackground = true;
            worker.Start();
            while (!job.done) yield return null;

            // null = clip too short to stretch; a moved stretchedAtSpeed means the user changed
            // speed while we crunched, so this result no longer matches the cache's speed.
            AudioClip sc = null;
            if (job.output != null && Mathf.Abs(stretchedAtSpeed - speed) <= 0.001f)
            {
                try
                {
                    sc = AudioClip.Create(rel + "@" + speed.ToString("0.00"),
                                          job.output.Length / channels, channels, freqHz, false, false);
                    sc.SetData(job.output, 0);
                }
                catch (Exception e)
                {
                    if (Plugin.Log != null) Plugin.Log.LogWarning("preserve-pitch stretch failed: " + e.Message);
                    sc = null;
                }
            }
            if (sc == null)
            {
                if (playToken == token) currentClipFactor = 1f;
                done(clip); yield break;
            }
            if (!stretchLogged)
            {
                stretchLogged = true;
                if (Plugin.Log != null)
                    Plugin.Log.LogInfo("preserve-pitch: time-stretch active, first clip baked at " + speed.ToString("0.00") + "x.");
            }
            // a concurrent stretch (preload vs. playback) may have cached this clip already
            AudioClip existing;
            if (stretched.TryGetValue(rel, out existing) && existing != null)
            {
                Destroy(sc);
                sc = existing;
            }
            else
            {
                if (stretched.Count > 32) FlushStretched();   // bound uncompressed-PCM memory
                stretched[rel] = sc;
            }
            if (playToken == token) currentClipFactor = speed;
            done(sc);
        }

        class StretchJob
        {
            readonly float[] input;
            readonly int channels;
            readonly int freq;
            readonly float speed;
            public volatile bool done;
            public float[] output;

            public StretchJob(float[] input, int channels, int freq, float speed)
            {
                this.input = input; this.channels = channels; this.freq = freq; this.speed = speed;
            }

            public void Run()
            {
                try { output = Wsola(input, channels, freq, speed); }
                catch (Exception) { output = null; }
                done = true;
            }
        }

        // With the bark channel, a flush can hit while another source is mid-clip (speed change
        // during a bark, cache cap with two barks in the air), so destroying everything outright
        // would truncate audible playback. In-use clips go to deferredDestroy and are reaped by
        // Update once their source releases them.
        readonly List<AudioClip> deferredDestroy = new List<AudioClip>();

        bool ClipInUse(AudioClip c)
        {
            if (src != null && src.clip == c && src.isPlaying) return true;
            if (barkSrcs != null)
                for (int i = 0; i < barkSrcs.Length; i++)
                    if (barkSrcs[i] != null && barkSrcs[i].clip == c && barkSrcs[i].isPlaying) return true;
            return false;
        }

        void SweepDeferred()
        {
            for (int i = deferredDestroy.Count - 1; i >= 0; i--)
            {
                AudioClip c = deferredDestroy[i];
                if (c != null && ClipInUse(c)) continue;
                if (c != null) Destroy(c);
                deferredDestroy.RemoveAt(i);
            }
        }

        void FlushStretched()
        {
            foreach (AudioClip c in stretched.Values)
            {
                if (c == null) continue;
                if (ClipInUse(c)) deferredDestroy.Add(c);
                else Destroy(c);
            }
            stretched.Clear();
        }

        static bool AllZero(float[] data)
        {
            for (int i = 0; i < data.Length; i++)
                if (data[i] != 0f) return false;
            return true;
        }

        // Time-stretch interleaved PCM by `speed` (2.0 -> half as long, same pitch). 40ms Hann
        // windows, 50% overlap-add; each analysis frame is picked within +-8ms of its nominal
        // position by waveform similarity against the natural continuation of the previous frame,
        // which is what avoids the metallic phasing of naive overlap-add. Offsets are searched on
        // a mono mixdown and applied to all channels. Returns null if the clip is too short.
        static float[] Wsola(float[] input, int channels, int freq, float speed)
        {
            int inFrames = input.Length / channels;
            int win = Mathf.Clamp((int)(freq * 0.040f) & ~1, 256, 8192);
            int hop = win / 2;
            int search = Mathf.Max(16, (int)(freq * 0.008f));
            int outFrames = (int)(inFrames / speed);
            if (inFrames < win * 2 || outFrames < win) return null;

            float[] mono;
            if (channels == 1) mono = input;
            else
            {
                mono = new float[inFrames];
                for (int i = 0; i < inFrames; i++)
                {
                    float s = 0f;
                    for (int c = 0; c < channels; c++) s += input[i * channels + c];
                    mono[i] = s / channels;
                }
            }

            float[] hann = new float[win];
            for (int j = 0; j < win; j++)
                hann[j] = 0.5f * (1f - Mathf.Cos(2f * Mathf.PI * j / (win - 1)));

            float[] output = new float[outFrames * channels];
            int prevStart = 0;
            for (int k = 0; ; k++)
            {
                int outPos = k * hop;
                if (outPos >= outFrames) break;
                // final windows write partially instead of stopping a full window early,
                // which would drop the clip's last word-ending at speeds > 1
                int writeLen = Mathf.Min(win, outFrames - outPos);
                int start = 0;
                if (k > 0)
                {
                    int ideal = (int)(outPos * speed);
                    int lo = Mathf.Max(0, ideal - search);
                    int hi = Mathf.Min(inFrames - win, ideal + search);
                    int natural = Mathf.Min(prevStart + hop, inFrames - win);
                    start = (hi <= lo) ? Mathf.Clamp(ideal, 0, inFrames - win)
                                       : BestOffset(mono, natural, lo, hi, hop);
                }
                prevStart = start;
                for (int j = 0; j < writeLen; j++)
                {
                    float w = hann[j];
                    int inIdx = (start + j) * channels;
                    int outIdx = (outPos + j) * channels;
                    for (int c = 0; c < channels; c++)
                        output[outIdx + c] += input[inIdx + c] * w;
                }
            }
            return output;
        }

        // Coarse-then-fine cross-correlation argmax: candidate starts in [lo, hi] scored against
        // the reference at `natural`, comparing `len` samples. Decimated taps keep this cheap
        // enough for the game's old Mono runtime.
        static int BestOffset(float[] mono, int natural, int lo, int hi, int len)
        {
            int best = lo;
            float bestScore = float.MinValue;
            for (int s = lo; s <= hi; s += 4)
            {
                float score = Corr(mono, s, natural, len);
                if (score > bestScore) { bestScore = score; best = s; }
            }
            int lo2 = Mathf.Max(lo, best - 3), hi2 = Mathf.Min(hi, best + 3);
            for (int s = lo2; s <= hi2; s++)
            {
                if (s == best) continue;
                float score = Corr(mono, s, natural, len);
                if (score > bestScore) { bestScore = score; best = s; }
            }
            return best;
        }

        static float Corr(float[] mono, int a, int b, int len)
        {
            float sum = 0f;
            for (int j = 0; j < len; j += 4)
                sum += mono[a + j] * mono[b + j];
            return sum;
        }

        // Load one OGG clip from disk into the cache. `done` receives the clip (or null on failure).
        public IEnumerator LoadClip(string rel, Action<AudioClip> done)
        {
            AudioClip existing;
            if (cache.TryGetValue(rel, out existing) && existing != null)
            {
                if (done != null) done(existing);
                yield break;
            }
            string full = Path.Combine(root, rel);
            string url;
            try { url = new Uri(full).AbsoluteUri; }        // file:///C:/...%20... — handles spaces
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("bad path " + full + ": " + e.Message);
                if (done != null) done(null);
                yield break;
            }
            WWW w = new WWW(url);
            yield return w;
            if (!string.IsNullOrEmpty(w.error))
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("load failed " + rel + ": " + w.error);
                if (done != null) done(null);
                yield break;
            }
            AudioClip clip = w.GetAudioClip(false, false, AudioType.OGGVORBIS);
            float start = Time.realtimeSinceStartup;   // Unity 4 has no unscaledDeltaTime
            while (clip != null && !clip.isReadyToPlay && (Time.realtimeSinceStartup - start) < 8f)
                yield return null;
            if (clip != null) cache[rel] = clip;
            if (done != null) done(clip);
        }

        // Preload a conversation's clips one at a time (avoid a burst of simultaneous WWW loads).
        public void Preload(List<string> rels)
        {
            StartCoroutine(PreloadSeq(rels));
        }

        IEnumerator PreloadSeq(List<string> rels)
        {
            for (int i = 0; i < rels.Count; i++)
            {
                AudioClip clip;
                if (!cache.TryGetValue(rels[i], out clip) || clip == null)
                {
                    AudioClip loaded = null;
                    yield return StartCoroutine(LoadClip(rels[i], delegate(AudioClip c) { loaded = c; }));
                    clip = loaded;
                }
                // warm the time-stretch cache too, so line start doesn't pay the stretch latency.
                // token -1 never matches playToken, so this can't touch currentClipFactor.
                if (clip != null && !stretchBroken && PreservePitch() && Mathf.Abs(Speed() - 1f) >= 0.025f)
                    yield return StartCoroutine(StretchAsync(rels[i], clip, -1, delegate(AudioClip c) { }));
            }
        }

        // One-time warm-up during the load screen: decode and silently play a single clip so the
        // OGG/Vorbis decoder and the audio pipeline are already initialized before the first real
        // line. Without this, the FIRST voiced conversation of the session pays that init cost as a
        // noticeable hitch (the plugin loads very early via the Camera entrypoint, so we wait for the
        // game's audio system to come up first). Aborts cleanly if a real line preempts us.
        public void Warmup()
        {
            StartCoroutine(WarmupSeq());
        }

        IEnumerator WarmupSeq()
        {
            float t0 = Time.realtimeSinceStartup;
            while (Time.realtimeSinceStartup - t0 < 1.5f) yield return null;   // let audio system init
            string rel = null;
            try
            {
                string clipsDir = Path.Combine(root, "clips");
                if (Directory.Exists(clipsDir))
                {
                    string[] files = Directory.GetFiles(clipsDir, "*.ogg");
                    if (files.Length > 0) rel = "clips/" + Path.GetFileName(files[0]);
                }
            }
            catch (Exception) { }
            if (rel == null) yield break;
            int myToken = playToken;
            AudioClip clip = null;
            yield return StartCoroutine(LoadClip(rel, delegate(AudioClip c) { clip = c; }));
            if (clip == null || src == null || playToken != myToken) yield break;   // preempted -> leave it alone
            float vol = src.volume;
            src.volume = 0f;
            src.clip = clip;
            src.Play();
            float p0 = Time.realtimeSinceStartup;
            while (playToken == myToken && src != null && src.isPlaying && (Time.realtimeSinceStartup - p0) < 0.2f)
                yield return null;
            if (playToken == myToken && src != null)
            {
                src.Stop();
                src.clip = null;
                src.volume = vol;
            }
            if (Plugin.Log != null) Plugin.Log.LogInfo("audio pipeline warmed up.");
        }
    }
}
