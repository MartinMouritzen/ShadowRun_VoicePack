using System;
using System.Reflection;
using HarmonyLib;

namespace SRRVoices
{
    // Template-variable variants.
    //
    // Shadowrun authors a line once and displays it several ways: "Greetings, young $(l.race)."
    // becomes human/elf/dwarf/ork/troll, "$(l.he)" becomes he or she. The pack ships a clip per
    // value under "<key>#<variantId>"; this class works out which id THIS playthrough is, so the
    // right one plays.
    //
    // The values are not guessed from the player object. The game already owns a substitution
    // routine (ParseTextExpansion), and asking it to expand "$(l.race)" returns exactly the word
    // the on-screen text will use — so the audio can never disagree with what is written, even if
    // a mod or a later patch changes how a metatype is spelled. If that method cannot be found the
    // resolver simply reports "no variant" and every line falls back to its generic clip, which is
    // the behaviour the pack had before variants existed.
    public static class Variants
    {
        static MethodInfo _expand;
        static bool _looked;
        static string _cached;          // "<gender>.<race>", e.g. "m.elf"
        static int _cachedFrame = -1;
        static string _announced = "";

        static MethodInfo Expander()
        {
            if (_looked) return _expand;
            _looked = true;
            foreach (Type t in AccessTools.AllTypes())
            {
                MethodInfo m;
                try
                {
                    m = t.GetMethod("ParseTextExpansion",
                        BindingFlags.Public | BindingFlags.NonPublic |
                        BindingFlags.Static | BindingFlags.Instance);
                }
                catch { continue; }
                if (m == null) continue;
                ParameterInfo[] ps = m.GetParameters();
                if (m.ReturnType == typeof(string) && ps.Length >= 1 && ps[0].ParameterType == typeof(string))
                {
                    _expand = m;
                    if (Plugin.Log != null)
                        Plugin.Log.LogInfo("variants: using " + t.FullName + ".ParseTextExpansion");
                    break;
                }
            }
            if (_expand == null && Plugin.Log != null)
                Plugin.Log.LogWarning("variants: ParseTextExpansion not found — every line uses its generic clip");
            return _expand;
        }

        static string Expand(string probe)
        {
            MethodInfo m = Expander();
            if (m == null) return null;
            try
            {
                ParameterInfo[] ps = m.GetParameters();
                object[] args = new object[ps.Length];
                args[0] = probe;
                for (int i = 1; i < ps.Length; i++)
                    args[i] = ps[i].ParameterType.IsValueType ? Activator.CreateInstance(ps[i].ParameterType) : null;
                object inst = null;
                if (!m.IsStatic)
                {
                    // An instance method needs the live manager; the scene owns exactly one.
                    inst = UnityEngine.Object.FindObjectOfType(m.DeclaringType);
                    if (inst == null) return null;
                }
                string s = m.Invoke(inst, args) as string;
                if (string.IsNullOrEmpty(s) || s == probe) return null;
                return s.Trim().ToLowerInvariant();
            }
            catch { return null; }
        }

        /// The game's own substitution applied to arbitrary text, or null when unavailable.
        /// Used by the text-hashed surfaces, which key their variants by the hash of the sentence
        /// as displayed rather than by a variant id.
        public static string ExpandText(string raw)
        {
            MethodInfo m = Expander();
            if (m == null || string.IsNullOrEmpty(raw)) return null;
            try
            {
                ParameterInfo[] ps = m.GetParameters();
                object[] args = new object[ps.Length];
                args[0] = raw;
                for (int i = 1; i < ps.Length; i++)
                    args[i] = ps[i].ParameterType.IsValueType ? Activator.CreateInstance(ps[i].ParameterType) : null;
                object inst = null;
                if (!m.IsStatic)
                {
                    inst = UnityEngine.Object.FindObjectOfType(m.DeclaringType);
                    if (inst == null) return null;
                }
                return m.Invoke(inst, args) as string;
            }
            catch { return null; }
        }

        /// "<gender>.<race>" for this playthrough, or null when it cannot be determined.
        /// Recomputed at most once per frame: a metatype cannot change mid-conversation, but the
        /// player can start a new game without the plugin reloading.
        public static string Current()
        {
            int frame = UnityEngine.Time.frameCount;
            if (frame == _cachedFrame) return _cached;
            _cachedFrame = frame;

            string race = Expand("$(l.race)");
            string he = Expand("$(l.he)");
            string g = he == null ? null : (he == "she" ? "f" : (he == "he" ? "m" : null));
            if (race != null && race.Length > 0 && !IsMetatype(race)) race = null;
            if (g == null && race == null) _cached = null;
            else if (g == null) _cached = race;
            else if (race == null) _cached = g;
            else _cached = g + "." + race;
            // Log the first resolution (and any later change) once. Whether the game's expander is
            // reachable from outside a conversation is the one thing that cannot be checked short
            // of running it, so say plainly which variant is in force.
            if (_cached != _announced)
            {
                _announced = _cached;
                if (Plugin.Log != null)
                    Plugin.Log.LogInfo("variants: this playthrough is '" +
                        (_cached ?? "(unresolved - using generic clips)") + "'");
            }
            return _cached;
        }

        static bool IsMetatype(string s)
        {
            return s == "human" || s == "elf" || s == "dwarf" || s == "ork" || s == "troll";
        }

        /// The pack lookup for a dialogue key, preferring the most specific variant that exists.
        /// Order matters: a line that varies on both axes ships "m.elf", one that varies on race
        /// alone ships "elf", gender alone ships "m". Falling through to `key` is always valid,
        /// because the generic clip is generated for every line whether it varies or not.
        public static bool TryGet(VoicePack pack, string key, out string[] clips)
        {
            clips = null;
            if (pack == null || key == null) return false;
            string v = Current();
            if (v != null)
            {
                if (pack.TryGet(key + "#" + v, out clips)) return true;
                int dot = v.IndexOf('.');
                if (dot > 0)
                {
                    if (pack.TryGet(key + "#" + v.Substring(dot + 1), out clips)) return true;   // race
                    if (pack.TryGet(key + "#" + v.Substring(0, dot), out clips)) return true;    // gender
                }
            }
            return pack.TryGet(key, out clips);
        }
    }
}
