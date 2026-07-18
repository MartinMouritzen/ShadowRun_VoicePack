using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
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
            if (src != null && src.isPlaying) src.pitch = v;   // apply to the line playing right now
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

        // Re-read volume/speed config and apply to whatever is playing right now (options sliders).
        public void ApplyLive()
        {
            if (src == null) return;
            src.volume = Vol();
            src.pitch = Speed();
        }

        public void StopAll()
        {
            playToken++;
            if (src != null) src.Stop();
        }

        public void PlaySequence(string[] relPaths)
        {
            playToken++;
            int myToken = playToken;
            if (src != null) src.Stop();
            StartCoroutine(PlaySeq(relPaths, myToken));
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
                src.volume = Vol();
                src.pitch = Speed();
                src.clip = clip;
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
                if (cache.ContainsKey(rels[i])) continue;
                yield return StartCoroutine(LoadClip(rels[i], null));
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
