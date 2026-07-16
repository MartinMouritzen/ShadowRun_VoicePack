using System;
using System.Security.Cryptography;
using System.Text;
using HarmonyLib;
using isogame;

namespace SRRVoices
{
    // Voice the "click to inspect" one-liners (InteractionBehaviorInspect). These are NOT
    // conversations, so ShowNodeText doesn't see them — they go through
    // InteractableObject.handleInspectInteraction, which reads interactionData.inspectInteraction.inspectText
    // and shows it as floating GM text. We key inspect clips by md5(rawInspectText) (see build_voicepack.py).
    [HarmonyPatch(typeof(InteractableObject), "handleInspectInteraction")]
    public static class Patch_Inspect
    {
        static void Postfix(InteractableObject __instance, bool __result)
        {
            if (Plugin.CfgEnabled == null || !Plugin.CfgEnabled.Value) return;
            if (Plugin.CfgInspect != null && !Plugin.CfgInspect.Value) return;   // inspects disabled in config
            if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value)
                Plugin.Log.LogInfo("handleInspectInteraction fired (result=" + __result + ")");   // diagnostic: does it fire at all?
            if (!__result || Plugin.Pack == null || Plugin.Player == null || __instance == null) return;
            try
            {
                InteractionBehaviorRoot data = __instance.interactionData;
                if (data == null || data.inspectInteraction == null) return;
                string raw = data.inspectInteraction.inspectText;
                if (string.IsNullOrEmpty(raw)) return;
                string key = "insp_" + Md5Hex16(raw);
                bool log = Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value;
                string[] clips;
                if (Plugin.Pack.TryGet(key, out clips))
                {
                    if (Plugin.InspectDebounced(key)) return;
                    if (log) Plugin.Log.LogInfo("play inspect " + key + " (" + clips.Length + " clips)");
                    Plugin.Player.PlaySequence(clips);
                }
                else if (log)
                {
                    // Diagnostic: the hook DID fire but no clip matched. Emit the computed key + the
                    // exact runtime text (quoted, length) so we can reconcile the md5.
                    Plugin.Log.LogInfo("inspect MISS " + key + " len=" + raw.Length + " text=<<" + raw + ">>");
                }
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("inspect hook: " + e.Message);
            }
        }

        // Must match Python: hashlib.md5(text.encode('utf-8')).hexdigest()[:16]
        internal static string Md5Hex16(string s)
        {
            MD5 md5 = MD5.Create();
            byte[] h = md5.ComputeHash(Encoding.UTF8.GetBytes(s));
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < h.Length; i++) sb.Append(h[i].ToString("x2"));
            return sb.ToString().Substring(0, 16);
        }
    }

    // The inline apartment inspects (computer, bank slip, trivid disc) are NOT prop
    // inspectInteractions and don't go through handleInspectInteraction. They're scene-script
    // "Display Text over Prop" actions, and the log proved DisplayTextOverProp itself isn't the
    // method the game calls. So we patch the whole family of floating-text methods by reflection.
    // For each call we play the matching narrator inspect clip if one exists (insp_<md5>), so
    // conversations/barks are unaffected; a shared debounce prevents doubling. Logging records
    // which method fired and the exact text so any remaining mismatch is diagnosable in one pass.
    public static class Patch_FloatingText
    {
        static readonly string[] NAMES = {
            "CreateGMText", "DisplayTextOverProp", "DisplayTextAtScreenPoint",
            "DisplayTextOverPoint", "DisplayTextInPopup", "FullscreenGMText", "ShowText",
            "DisplayTextOverActor"   // combat barks (spoken by an actor) -> bark_<md5>
        };

        public static System.Collections.Generic.List<System.Reflection.MethodBase> FindAll()
        {
            var found = new System.Collections.Generic.List<System.Reflection.MethodBase>();
            var flags = System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic |
                        System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Static;
            foreach (var t in typeof(ConversationManager).Assembly.GetTypes())
            {
                System.Reflection.MethodInfo[] ms;
                try { ms = t.GetMethods(flags); } catch (Exception) { continue; }
                foreach (var m in ms)
                {
                    if (Array.IndexOf(NAMES, m.Name) < 0) continue;
                    if (m.IsAbstract || m.ContainsGenericParameters) continue;
                    bool hasStr = false;
                    foreach (var p in m.GetParameters()) if (p.ParameterType == typeof(string)) { hasStr = true; break; }
                    if (hasStr) found.Add(m);
                }
            }
            return found;
        }

        public static void Postfix(object[] __args, System.Reflection.MethodBase __originalMethod)
        {
            if (Plugin.CfgEnabled == null || !Plugin.CfgEnabled.Value) return;
            if (Plugin.Pack == null || Plugin.Player == null || __args == null) return;
            try
            {
                string text = null;
                foreach (var a in __args)
                {
                    string s = a as string;
                    if (s != null && s.Trim().Length > 3) { text = s.Trim(); break; }
                }
                if (text == null) return;
                bool log = Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value;
                string md5 = Patch_Inspect.Md5Hex16(text);
                string[] clips = null;
                string key = "bark_" + md5;                                   // combat bark?
                if (!Plugin.Pack.TryGet(key, out clips)) { key = "insp_" + md5; if (!Plugin.Pack.TryGet(key, out clips)) clips = null; }  // else inspect?
                if (clips != null && clips.Length > 0)
                {
                    if (key[0] == 'b' && Plugin.CfgBarks != null && !Plugin.CfgBarks.Value) return;      // bark_ disabled
                    if (key[0] == 'i' && Plugin.CfgInspect != null && !Plugin.CfgInspect.Value) return;  // insp_ disabled
                    if (Plugin.InspectDebounced(key)) return;
                    if (log) Plugin.Log.LogInfo("play FT[" + __originalMethod.Name + "] " + key + " (" + clips.Length + " clips)");
                    Plugin.Player.PlaySequence(clips);
                }
                else if (log && text.Length > 12 && text.IndexOf(' ') > 0)
                {
                    // inspect-like text that DIDN'T match a clip -> shows the exact runtime text + method
                    Plugin.Log.LogInfo("FT[" + __originalMethod.Name + "] no-match len=" + text.Length + " text=<<" + text + ">>");
                }
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("FT hook: " + e.Message);
            }
        }
    }
}
