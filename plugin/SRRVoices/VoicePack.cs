using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;

namespace SRRVoices
{
    // Loads voicepack.index (TSV: "<convoId>_<nodeIndex>\t<clip1>\t<clip2>...").
    // TSV is used instead of JSON because .NET 3.5 / Unity 4 has no reliable built-in JSON parser.
    public class VoicePack
    {
        readonly Dictionary<string, string[]> lines = new Dictionary<string, string[]>();
        public string Root;    // absolute dir containing voicepack.index and clips/

        public int LineCount { get { return lines.Count; } }

        public bool TryGet(string key, out string[] clips)
        {
            return lines.TryGetValue(key, out clips);
        }

        public static VoicePack Load(string vpDir, ManualLogSource log)
        {
            string idx = Path.Combine(vpDir, "voicepack.index");
            if (!File.Exists(idx))
            {
                if (log != null) log.LogWarning("voicepack.index not found at " + idx);
                return null;
            }
            var vp = new VoicePack();
            vp.Root = vpDir;
            int bad = 0;
            foreach (string raw in File.ReadAllLines(idx))
            {
                string line = raw;
                if (line.Length == 0 || line[0] == '#') continue;
                string[] parts = line.Split('\t');
                if (parts.Length < 2) { bad++; continue; }
                string key = parts[0];
                var clips = new string[parts.Length - 1];
                Array.Copy(parts, 1, clips, 0, clips.Length);
                vp.lines[key] = clips;
            }
            if (bad > 0 && log != null) log.LogWarning("voicepack: skipped " + bad + " malformed rows");
            return vp;
        }

        // All unique clip paths referenced by the given node keys (for preloading a conversation).
        public List<string> ClipsForKeys(IEnumerable<string> keys)
        {
            var seen = new HashSet<string>();
            var outp = new List<string>();
            foreach (string k in keys)
            {
                string[] clips;
                if (lines.TryGetValue(k, out clips))
                    foreach (string c in clips)
                        if (seen.Add(c)) outp.Add(c);
            }
            return outp;
        }
    }
}
