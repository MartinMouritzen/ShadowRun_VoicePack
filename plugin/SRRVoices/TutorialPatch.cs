using System;
using System.Reflection;
using HarmonyLib;
using isogame;

namespace SRRVoices
{
    // The engine's own HELP SCREEN tutorials ("Spend your Karma", "Etiquette", the character
    // creation panels). These are NOT the scene popups: DisplayTextInPopup is authored per map and
    // is already covered by Patch_FloatingText, while these come from ShowHelpScreenPopup and their
    // text lives in the UI string table, not in any scene. Nothing hooked them, so they had never
    // made a sound - which is exactly what it looked like from the outside: "the tutorial messages
    // still don't play".
    //
    // Keyed tut_<md5(body text)> and voiced by the Tutorial part, the same voice Tyranny's UI
    // narrator uses. The body is read off the popup at runtime rather than predicted, so a string
    // the extractor missed simply logs a MISS instead of playing the wrong clip.
    public static class Patch_HelpScreen
    {
        // The popup is built by one of these; which one varies by build, so take whichever exists.
        static readonly string[] NAMES = { "CreateHelpScreenPopup", "ShowHelpScreenPopup", "ShowHelpScreen" };
        static string _last;
        static float _lastAt;

        public static System.Collections.Generic.List<MethodBase> FindAll()
        {
            var found = new System.Collections.Generic.List<MethodBase>();
            var flags = BindingFlags.Public | BindingFlags.NonPublic |
                        BindingFlags.Instance | BindingFlags.Static;
            foreach (var t in typeof(ConversationManager).Assembly.GetTypes())
            {
                MethodInfo[] ms;
                try { ms = t.GetMethods(flags); } catch (Exception) { continue; }
                foreach (var m in ms)
                {
                    if (Array.IndexOf(NAMES, m.Name) < 0) continue;
                    if (m.IsAbstract || m.ContainsGenericParameters) continue;
                    found.Add(m);
                }
            }
            return found;
        }

        // Any string argument long enough to be the body rather than a header or a button label.
        static string BodyOf(object[] args)
        {
            string best = null;
            if (args == null) return null;
            foreach (object a in args)
            {
                string s = a as string;
                if (string.IsNullOrEmpty(s)) continue;
                if (best == null || s.Length > best.Length) best = s;
            }
            return (best != null && best.Length >= 60) ? best : null;
        }

        public static void Postfix(object[] __args, MethodBase __originalMethod)
        {
            try
            {
                if (Plugin.CfgEnabled == null || !Plugin.CfgEnabled.Value) return;
                if (Plugin.Pack == null || Plugin.Player == null) return;
                string body = BodyOf(__args);
                if (body == null) return;
                body = System.Text.RegularExpressions.Regex.Replace(body, @"\s+", " ").Trim();

                // The screen is rebuilt on resize and on every navigation back to it, so the same
                // popup can fire several times; without this the clip restarts under itself.
                float now = UnityEngine.Time.realtimeSinceStartup;
                if (body == _last && now - _lastAt < 3f) return;
                _last = body; _lastAt = now;

                string key = "tut_" + Patch_Inspect.Md5Hex16(body);
                string[] clips;
                bool log = Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value;
                if (Plugin.Pack.TryGet(key, out clips))
                {
                    if (log) Plugin.Log.LogInfo("play tutorial " + key + " (" + clips.Length + " clips)");
                    Plugin.Player.PlaySequence(clips);
                }
                else if (log)
                {
                    // The exact key and the first words, so an unvoiced tutorial can be added
                    // without having to guess which string the game actually showed.
                    Plugin.Log.LogInfo("tutorial MISS " + key + " via " + __originalMethod.Name +
                                       " len=" + body.Length + " :: " +
                                       body.Substring(0, Math.Min(70, body.Length)));
                }
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("tutorial hook: " + e.Message);
            }
        }
    }
}
