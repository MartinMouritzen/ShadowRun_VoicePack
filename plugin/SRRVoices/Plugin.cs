using System;
using System.IO;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace SRRVoices
{
    [BepInPlugin(GUID, "SRR AI Voices", "1.4.0")]
    public class Plugin : BaseUnityPlugin
    {
        public const string GUID = "com.mmo.srrvoices";

        public static Plugin Instance;
        public static ManualLogSource Log;
        public static ConfigEntry<bool> CfgEnabled;
        public static ConfigEntry<bool> CfgInspect;
        public static ConfigEntry<bool> CfgBarks;
        public static ConfigEntry<bool> CfgLoadScreens;
        public static ConfigEntry<float> CfgVolume;
        public static ConfigEntry<float> CfgSpeed;
        public static ConfigEntry<bool> CfgPreservePitch;
        public static ConfigEntry<float> CfgSegmentGap;
        public static ConfigEntry<bool> CfgBorderless;
        public static ConfigEntry<bool> CfgLogLines;
        public static ConfigEntry<bool> CfgPortraits;
        public static ConfigEntry<float> CfgPdaNudgeX;
        public static ConfigEntry<float> CfgPdaNudgeY;

        public static VoicePack Pack;
        public static VoicePlayer Player;

        // Shared inspect debounce: an inspect can be shown via both handleInspectInteraction and the
        // scene-script DisplayTextOverProp path in the same frame. Whichever fires first plays; the
        // other is suppressed for a short window so the line isn't spoken twice.
        static float _lastInspectTime = -10f;
        static string _lastInspectKey = "";
        public static bool InspectDebounced(string key)
        {
            float now = UnityEngine.Time.realtimeSinceStartup;
            if (key == _lastInspectKey && (now - _lastInspectTime) < 0.8f) return true;
            _lastInspectKey = key; _lastInspectTime = now;
            return false;
        }

        void Awake()
        {
            Instance = this;
            Log = Logger;

            CfgEnabled = Config.Bind("General", "Enabled", true, "Master enable for AI voices.");
            CfgInspect = Config.Bind("General", "VoiceInspects", true, "Voice the 'examine object' inspect one-liners (narrator). Set false to keep inspects silent.");
            CfgBarks = Config.Bind("General", "VoiceCombatBarks", true, "Voice combat barks (lines actors shout in a fight). Set false to keep barks silent.");
            CfgLoadScreens = Config.Bind("General", "VoiceLoadScreens", true, "Narrate the loading-screen scene descriptions. Set false to keep load screens silent.");
            CfgVolume = Config.Bind("General", "Volume", 1f, "Voice volume, 0..1.");
            CfgSpeed = Config.Bind("General", "PlaybackSpeed", 1f,
                "Voice playback speed multiplier (1 = normal, clamped 0.5..2).");
            CfgPreservePitch = Config.Bind("General", "PreservePitch", true,
                "Keep the voice's natural pitch when PlaybackSpeed is not 1.0 (time-stretch). Set false for raw tape-style speedup, where pitch rises with speed.");
            CfgSegmentGap = Config.Bind("General", "SegmentGap", 0.3f,
                "Pause in seconds between a line's segments (narrator -> character swap). 0 = instant.");
            CfgBorderless = Config.Bind("Display", "BorderlessFullscreen", false,
                "Force borderless fullscreen at desktop resolution on startup.");
            CfgPortraits = Config.Bind("General", "AIPortraits", true,
                "Show AI-generated portraits for characters the game ships without one. "
                + "Characters with their own portrait art are never changed.");
            CfgLogLines = Config.Bind("Debug", "LogLines", true,
                "Log each played / missed dialogue node key to the BepInEx log.");
            CfgPdaNudgeX = Config.Bind("Options", "PdaPanelNudgeX", 0f,
                "Horizontal nudge (NGUI pixels) for the voice-settings side panel on the in-game Escape menu.");
            CfgPdaNudgeY = Config.Bind("Options", "PdaPanelNudgeY", 0f,
                "Vertical nudge (NGUI pixels) for the voice-settings side panel on the in-game Escape menu.");

            string dir = Path.Combine(Paths.PluginPath, "SRRVoices");
            string vpDir = Path.Combine(dir, "voicepack");
            Pack = VoicePack.Load(vpDir, Log);
            if (Pack != null)
                Log.LogInfo("Voicepack loaded: " + Pack.LineCount + " voiced nodes from " + vpDir);
            else
                Log.LogWarning("No voicepack found at " + vpDir + " — plugin will run but play nothing.");

            var go = new GameObject("SRRVoicesPlayer");
            DontDestroyOnLoad(go);
            go.hideFlags = HideFlags.HideAndDontSave;
            Player = go.AddComponent<VoicePlayer>();
            if (Pack != null) { Player.SetRoot(Pack.Root); Player.Warmup(); }

            var harmony = new Harmony(GUID);
            try
            {
                harmony.PatchAll();
                Log.LogInfo("Harmony patches applied (ShowNodeText / StartConversation / EndConversation).");
            }
            catch (Exception e)
            {
                Log.LogError("Harmony PatchAll failed: " + e);
            }
            // Manual, isolated patch for the scene-script inspect path (computer / bank slip / etc.).
            // Kept out of PatchAll so a missing method can't take down the core patches.
            try
            {
                var post = new HarmonyMethod(typeof(Patch_FloatingText).GetMethod("Postfix"));
                var methods = Patch_FloatingText.FindAll();
                int n = 0;
                foreach (var m in methods)
                {
                    try { harmony.CreateProcessor(m).AddPostfix(post).Patch(); n++; }
                    catch (Exception e) { Log.LogWarning("FT patch skip " + m.DeclaringType.Name + "." + m.Name + ": " + e.Message); }
                }
                Log.LogInfo("Patched " + n + "/" + methods.Count + " floating-text methods (inline inspects).");
            }
            catch (Exception e)
            {
                Log.LogWarning("Floating-text patch setup failed: " + e.Message);
            }

            // Load-screen narration hook (isolated: SceneLoader may differ in sequels).
            try
            {
                var slType = typeof(ConversationManager).Assembly.GetType("SceneLoader");
                var lsMethod = (slType == null) ? null : HarmonyLib.AccessTools.Method(slType, "setupLoadScreenData", null, null);
                if (lsMethod != null)
                {
                    harmony.CreateProcessor(lsMethod)
                           .AddPostfix(new HarmonyMethod(typeof(Patch_LoadScreen).GetMethod("Postfix")))
                           .Patch();
                    Log.LogInfo("Load-screen narration hook installed (SceneLoader.setupLoadScreenData).");
                }
                else Log.LogWarning("SceneLoader.setupLoadScreenData not found — load screens stay unvoiced.");

                // Stop narration when the loading screen goes away (Continue pressed or auto-continue).
                var tlsType = typeof(ConversationManager).Assembly.GetType("TempLoadScene");
                var closePost = new HarmonyMethod(typeof(Patch_LoadScreen).GetMethod("ClosePostfix"));
                int closeHooks = 0;
                if (tlsType != null)
                {
                    foreach (string mName in new string[] { "CurtainsUp", "Hide", "Cleanup" })
                    {
                        var m = HarmonyLib.AccessTools.Method(tlsType, mName, null, null);
                        if (m == null) continue;
                        try { harmony.CreateProcessor(m).AddPostfix(closePost).Patch(); closeHooks++; }
                        catch (Exception e) { Log.LogWarning("loadscreen close patch skip " + mName + ": " + e.Message); }
                    }
                }
                Log.LogInfo("Load-screen close hooks installed on " + closeHooks + " TempLoadScene methods.");

                // Narration starts only when the screen declares it will WAIT for the player.
                if (tlsType != null)
                {
                    var reqM = HarmonyLib.AccessTools.Method(tlsType, "SetRequiresContinueButton", null, null);
                    if (reqM != null)
                    {
                        harmony.CreateProcessor(reqM)
                               .AddPostfix(new HarmonyMethod(typeof(Patch_LoadScreen).GetMethod("RequireContinuePostfix")))
                               .Patch();
                        Patch_LoadScreen.ContinueGateAvailable = true;
                        Log.LogInfo("Load-screen continue-gate hook installed (SetRequiresContinueButton).");
                    }
                    else Log.LogWarning("SetRequiresContinueButton not found — loadscreen narration plays unconditionally.");
                }
            }
            catch (Exception e)
            {
                Log.LogWarning("Load-screen patch failed: " + e.Message);
            }

            // Options-screen slider injection (isolated: UI classes may differ in sequels).
            try
            {
                var osType = typeof(ConversationManager).Assembly.GetType("OptionsScreen");
                var osInit = (osType == null) ? null : HarmonyLib.AccessTools.Method(osType, "Initialize", null, null);
                if (osInit != null)
                {
                    harmony.CreateProcessor(osInit)
                           .AddPostfix(new HarmonyMethod(typeof(Patch_Options).GetMethod("Postfix")))
                           .Patch();
                    Log.LogInfo("Options-screen voice sliders hook installed (OptionsScreen.Initialize).");
                }
                else Log.LogWarning("OptionsScreen.Initialize not found — no in-game voice sliders.");

                // The in-game Escape menu options live on the PDA (PDAAnchor) with IDENTICAL
                // slider field names, so the same injection postfix works on its Awake.
                var pdaType = typeof(ConversationManager).Assembly.GetType("PDAAnchor");
                var pdaAwake = (pdaType == null) ? null : HarmonyLib.AccessTools.Method(pdaType, "Awake", null, null);
                if (pdaAwake != null)
                {
                    harmony.CreateProcessor(pdaAwake)
                           .AddPostfix(new HarmonyMethod(typeof(Patch_Options).GetMethod("Postfix")))
                           .Patch();
                    Log.LogInfo("PDA (Escape menu) voice sliders hook installed (PDAAnchor.Awake).");
                }
                else Log.LogWarning("PDAAnchor.Awake not found — Escape-menu voice sliders unavailable.");
            }
            catch (Exception e)
            {
                Log.LogWarning("Options-screen patch failed: " + e.Message);
            }

            try
            {
                PortraitPatches.Load(Path.Combine(dir, "portraits"));
                PortraitPatches.Apply(harmony);
            }
            catch (Exception e)
            {
                Log.LogWarning("AI portraits unavailable: " + e.Message);
            }

            if (CfgBorderless.Value)
            {
                try { BorderlessWindow.Apply(); Log.LogInfo("Borderless fullscreen applied."); }
                catch (Exception e) { Log.LogWarning("Borderless fullscreen failed: " + e.Message); }
            }

            Log.LogInfo("SRR AI Voices ready.");
        }
    }
}
