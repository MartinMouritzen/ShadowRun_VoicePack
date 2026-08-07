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
        // What the index looked like when this was loaded, so a later sync can be spotted.
        long stampTicks, stampLen;

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
            var fi = new FileInfo(idx);
            vp.stampTicks = fi.LastWriteTimeUtc.Ticks;
            vp.stampLen = fi.Length;
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

        // Has the manifest been rewritten since this pack was read?
        //
        // The lab syncs itself now, so the file under a live game changes while you play. Before
        // this, the session kept whatever manifest it read at startup: every line voiced since
        // launch logged "no VO" and the mod looked broken, when in fact the clip was sitting on
        // disk two directories away. Only the index is stat'ed — clips are content-hash named and
        // immutable, so nothing already loaded can go stale.
        public bool IndexChanged()
        {
            try
            {
                var fi = new FileInfo(Path.Combine(Root, "voicepack.index"));
                if (!fi.Exists) return false;
                return fi.LastWriteTimeUtc.Ticks != stampTicks || fi.Length != stampLen;
            }
            catch (Exception) { return false; }
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
