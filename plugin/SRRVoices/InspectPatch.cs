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

    // Loading screens: SceneLoader.setupLoadScreenData populates the load-screen UI from
    // sceneDef. The narration text is SceneDef.scene_synopsis (protobuf field 22) — it is scene
    // DATA, not baked into the loadingImage_* art. Key = bark_<md5(synopsis.Trim())>, matching
    // tools/extract_loadscreens.py. Patched manually (isolated try) from Plugin.Awake so a
    // missing method in a sequel can't take down the core patches.
    public static class Patch_LoadScreen
    {
        // token of the narration we started for the current load screen; -1 = none
        internal static int NarrationToken = -1;

        // Narration stashed until the game declares the screen will WAIT for the player.
        // Save-game loads (main menu Continue) never arm the continue button, so their
        // narration must never start - it would just be cut off by the auto-continue.
        static string[] pendingClips = null;
        static string pendingKey = null;

        // Set from Plugin.Awake when the SetRequiresContinueButton hook installed. Without it
        // (a sequel with a different loader?) we keep the old play-immediately behavior.
        internal static bool ContinueGateAvailable = false;

        // Postfixed onto TempLoadScene.SetRequiresContinueButton: this screen waits for the
        // player, so any stashed narration can start now.
        public static void RequireContinuePostfix()
        {
            try
            {
                if (pendingClips == null || Plugin.Player == null) return;
                bool log = Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value;
                if (log && Plugin.Log != null) Plugin.Log.LogInfo("play loadscreen " + pendingKey + " (continue button confirmed)");
                Plugin.Player.PlaySequence(pendingClips);
                NarrationToken = Plugin.Player.CurrentToken();
                pendingClips = null; pendingKey = null;
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("loadscreen continue hook: " + e.Message);
            }
        }

        // Postfixed onto TempLoadScene.CurtainsUp/Hide/Cleanup: the loading screen is going away
        // (auto-continue or the player pressed Continue) — stop the narration IF it is still the
        // active playback. A conversation line started after bumps the token, so it survives.
        public static void ClosePostfix()
        {
            try
            {
                if (pendingClips != null)
                {
                    if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value && Plugin.Log != null)
                        Plugin.Log.LogInfo("loadscreen closed without continue button — narration skipped.");
                    pendingClips = null; pendingKey = null;
                }
                if (Plugin.Player == null || NarrationToken < 0) return;
                if (Plugin.Player.CurrentToken() == NarrationToken)
                {
                    Plugin.Player.StopAll();
                    if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value && Plugin.Log != null)
                        Plugin.Log.LogInfo("loadscreen closed — narration stopped.");
                }
                NarrationToken = -1;
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("loadscreen close hook: " + e.Message);
            }
        }

        // Is the load screen's continue button already armed? (SceneLoader.tempLoadScene
        // .NeedsContinueButton via reflection; false when absent/unknowable.)
        static bool TlsNeedsContinue(object sceneLoader)
        {
            try
            {
                var f = HarmonyLib.AccessTools.Field(sceneLoader.GetType(), "tempLoadScene");
                object tls = (f == null) ? null : f.GetValue(sceneLoader);
                if (tls == null) return false;
                var p = HarmonyLib.AccessTools.Property(tls.GetType(), "NeedsContinueButton");
                return p != null && (bool)p.GetValue(tls, null);
            }
            catch (Exception) { return false; }
        }

        public static void Postfix(object __instance)
        {
            if (Plugin.CfgEnabled == null || !Plugin.CfgEnabled.Value) return;
            if (Plugin.CfgLoadScreens != null && !Plugin.CfgLoadScreens.Value) return;
            if (Plugin.Pack == null || Plugin.Player == null || __instance == null) return;
            try
            {
                var fld = HarmonyLib.AccessTools.Field(__instance.GetType(), "sceneDef");
                if (fld == null) return;
                SceneDef def = fld.GetValue(__instance) as SceneDef;
                if (def == null || string.IsNullOrEmpty(def.scene_synopsis)) return;
                string text = def.scene_synopsis.Trim();
                if (text.Length < 4) return;
                string key = "bark_" + Patch_Inspect.Md5Hex16(text);
                bool log = Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value;
                string[] clips;
                if (Plugin.Pack.TryGet(key, out clips))
                {
                    if (Plugin.InspectDebounced(key)) return;   // setup can run more than once per load
                    if (!ContinueGateAvailable || TlsNeedsContinue(__instance))
                    {
                        // gate unavailable, or continue button already armed -> play right away
                        if (log) Plugin.Log.LogInfo("play loadscreen " + key + " (" + clips.Length + " clips)");
                        Plugin.Player.PlaySequence(clips);
                        NarrationToken = Plugin.Player.CurrentToken();
                    }
                    else
                    {
                        // wait for SetRequiresContinueButton; a save-load never calls it, and its
                        // auto-continuing screen must stay silent (narration would be cut off).
                        pendingClips = clips; pendingKey = key;
                        if (log) Plugin.Log.LogInfo("loadscreen narration pending " + key + " (waiting for continue-button signal)");
                    }
                }
                else if (log)
                {
                    Plugin.Log.LogInfo("loadscreen MISS " + key + " len=" + text.Length);
                }
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("loadscreen hook: " + e.Message);
            }
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
            "DisplayTextOverActor",  // combat barks (spoken by an actor) -> bark_<md5>
            "OpenLoadScreen"         // DIAGNOSTIC: loading-screen text (object[] args) -> reveal via log
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
                    // Two families carry the text differently: CreateGMText/ShowText take a direct
                    // string param; the DisplayTextOver* family (incl. combat barks via
                    // DisplayTextOverActor) takes (context, object[] args) and puts the text INSIDE
                    // the object[]. Hook both shapes.
                    bool hookable = false;
                    foreach (var p in m.GetParameters())
                        if (p.ParameterType == typeof(string) || p.ParameterType == typeof(object[])) { hookable = true; break; }
                    if (hookable) found.Add(m);
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
                    // barks/DisplayTextOver* pass the text inside an object[] args array
                    object[] arr = a as object[];
                    if (arr != null)
                    {
                        foreach (var o in arr)
                        {
                            string os = o as string;
                            if (os != null && os.Trim().Length > 3) { text = os.Trim(); break; }
                        }
                        if (text != null) break;
                    }
                }
                if (text == null) return;
                bool log = Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value;
                // OpenLoadScreen is hooked for DIAGNOSTIC logging only. Loadscreen narration is
                // owned by Patch_LoadScreen (continue-button gating, NarrationToken stop-on-close);
                // playing its bark_ key here would bypass all of that.
                if (__originalMethod.Name == "OpenLoadScreen")
                {
                    if (log) Plugin.Log.LogInfo("FT[OpenLoadScreen] len=" + text.Length + " (playback owned by loadscreen path)");
                    return;
                }
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
                    // Combat barks go to the bark channel: they never truncate an already-playing
                    // bark (simultaneous shouts overlap) and never preempt dialogue/narration.
                    if (key[0] == 'b') Plugin.Player.PlayBark(clips);
                    else Plugin.Player.PlaySequence(clips);
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
