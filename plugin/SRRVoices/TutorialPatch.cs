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
        // The help-screen methods carry no text: the character-creation screen has one method per
        // popup (OpenPopupSpend for "Spend your Karma", OpenPopupEtiquette, OpenPopupTotem...) and
        // they look their own text up, handing it to the popup system as a PopupContents object.
        // Hooking them by name therefore yields nothing, which is exactly what the first attempt
        // did: 3/3 methods patched, not one line of audio. Anything that RECEIVES a PopupContents
        // is the real seam, and that is found by parameter type rather than by guessing names.
        static readonly string[] NAMES = {
            "CreateHelpScreenPopup", "ShowHelpScreenPopup", "ShowHelpScreen",
            "OpenPopupSpend", "OpenPopupEtiquette", "OpenPopupTotem", "OpenPopupIntro",
            "OpenPopupMageVision", "OpenPopupLaunch", "CreateFullscreenPopup",
            "CreateUnspentKarmaPopup",
        };
        const string CONTENTS = "PopupContents";
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
                    if (m.IsAbstract || m.ContainsGenericParameters) continue;
                    bool want = Array.IndexOf(NAMES, m.Name) >= 0;
                    if (!want)
                    {
                        foreach (var pi in m.GetParameters())
                            if (pi.ParameterType != null && pi.ParameterType.Name == CONTENTS) { want = true; break; }
                    }
                    if (want && !found.Contains(m)) found.Add(m);
                }
            }
            return found;
        }

        // Any string argument long enough to be the body rather than a header or a button label.
        // The longest string on or in the arguments: a plain string argument when there is one,
        // otherwise the body carried on the PopupContents. Headers and button labels are short, so
        // "longest" finds the body without needing that field's name in this particular build.
        static string LongestString(object o)
        {
            if (o == null) return null;
            string s = o as string;
            if (s != null) return s;
            Type t = o.GetType();
            if (t.IsPrimitive) return null;
            string best = null;
            var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
            foreach (var f in t.GetFields(flags))
            {
                if (f.FieldType != typeof(string)) continue;
                try { string v = f.GetValue(o) as string;
                      if (v != null && (best == null || v.Length > best.Length)) best = v; }
                catch (Exception) { }
            }
            foreach (var pr in t.GetProperties(flags))
            {
                if (pr.PropertyType != typeof(string) || pr.GetIndexParameters().Length > 0) continue;
                try { string v = pr.GetValue(o, null) as string;
                      if (v != null && (best == null || v.Length > best.Length)) best = v; }
                catch (Exception) { }
            }
            return best;
        }

        static string BodyOf(object[] args)
        {
            string best = null;
            if (args == null) return null;
            foreach (object a in args)
            {
                string s = LongestString(a);
                if (string.IsNullOrEmpty(s)) continue;
                if (best == null || s.Length > best.Length) best = s;
            }
            return (best != null && best.Length >= 60) ? best : null;
        }

        // Any string held by an object, one level deep: the popup's text is set on a field or a
        // property somewhere, and naming it is the whole point of the probe.
        static void Describe(System.Text.StringBuilder sb, string label, object o)
        {
            if (o == null) { sb.Append("\n").Append(label).Append("=null"); return; }
            string s = o as string;
            if (s != null) { sb.Append("\n").Append(label).Append("(string)=").Append(Trim(s)); return; }
            Type t = o.GetType();
            sb.Append("\n").Append(label).Append('(').Append(t.Name).Append(')');
            var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
            foreach (var f in t.GetFields(flags))
            {
                if (f.FieldType != typeof(string)) continue;
                try { string v = f.GetValue(o) as string;
                      if (!string.IsNullOrEmpty(v)) sb.Append("\n     .").Append(f.Name).Append("=").Append(Trim(v)); }
                catch (Exception) { }
            }
            foreach (var pr in t.GetProperties(flags))
            {
                if (pr.PropertyType != typeof(string) || pr.GetIndexParameters().Length > 0) continue;
                try { string v = pr.GetValue(o, null) as string;
                      if (!string.IsNullOrEmpty(v)) sb.Append("\n     .").Append(pr.Name).Append("=").Append(Trim(v)); }
                catch (Exception) { }
            }
        }
        static string Trim(string v)
        {
            v = System.Text.RegularExpressions.Regex.Replace(v, @"\s+", " ").Trim();
            return v.Length > 90 ? v.Substring(0, 90) + "..." : v;
        }

        public static void Postfix(object __instance, object[] __args, MethodBase __originalMethod)
        {
            try
            {
                if (Plugin.CfgEnabled == null || !Plugin.CfgEnabled.Value) return;
                if (Plugin.Pack == null || Plugin.Player == null) return;
                string body = BodyOf(__args);
                if (body == null)
                {
                    // DIAGNOSTIC: the hook installs (3/3 patched) but never yields text, so the
                    // body is not in the arguments. Dump the real signature and anything
                    // string-shaped on the arguments and on the popup itself, so the source can be
                    // identified from one log rather than guessed at.
                    try
                    {
                        var sb = new System.Text.StringBuilder();
                        sb.Append("tutorial PROBE ").Append(__originalMethod.DeclaringType.Name)
                          .Append('.').Append(__originalMethod.Name).Append('(');
                        foreach (var pi in __originalMethod.GetParameters())
                            sb.Append(pi.ParameterType.Name).Append(' ').Append(pi.Name).Append(", ");
                        sb.Append(") args=").Append(__args == null ? -1 : __args.Length);
                        if (__args != null)
                            for (int i = 0; i < __args.Length; i++)
                                Describe(sb, "  arg" + i, __args[i]);
                        Describe(sb, "  instance", __instance);
                        Plugin.Log.LogInfo(sb.ToString());
                    }
                    catch (Exception pe) { Plugin.Log.LogWarning("probe: " + pe.Message); }
                    return;
                }
                body = System.Text.RegularExpressions.Regex.Replace(body, @"\s+", " ").Trim();

                // The screen is rebuilt on resize and on every navigation back to it, so the same
                // popup can fire several times; without this the clip restarts under itself.
                float now = UnityEngine.Time.realtimeSinceStartup;
                if (body == _last && now - _lastAt < 3f) return;
                _last = body; _lastAt = now;

                string key = "tut_" + Patch_Inspect.Md5Hex16(body);
                string[] clips;
                bool log = Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value;
                // Some popups append a live counter to the body ("...can only be chosen once. 0/1"),
                // which changes the hash every time the count changes. The pack therefore also
                // carries a key over the first 90 characters, which nothing appended can disturb.
                if (!Plugin.Pack.TryGet(key, out clips) && body.Length >= 40)
                {
                    string head = body.Substring(0, Math.Min(90, body.Length));
                    string pkey = "tutp_" + Patch_Inspect.Md5Hex16(head);
                    if (Plugin.Pack.TryGet(pkey, out clips)) key = pkey;
                }
                if (clips != null || Plugin.Pack.TryGet(key, out clips))
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
