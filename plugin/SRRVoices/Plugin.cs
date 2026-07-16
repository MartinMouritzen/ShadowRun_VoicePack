using System;
using System.IO;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace SRRVoices
{
    [BepInPlugin(GUID, "SRR AI Voices", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        public const string GUID = "com.mmo.srrvoices";

        public static Plugin Instance;
        public static ManualLogSource Log;
        public static ConfigEntry<bool> CfgEnabled;
        public static ConfigEntry<bool> CfgInspect;
        public static ConfigEntry<bool> CfgBarks;
        public static ConfigEntry<float> CfgVolume;
        public static ConfigEntry<float> CfgSegmentGap;
        public static ConfigEntry<bool> CfgBorderless;
        public static ConfigEntry<bool> CfgLogLines;

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
            CfgVolume = Config.Bind("General", "Volume", 0.9f, "Voice volume, 0..1.");
            CfgSegmentGap = Config.Bind("General", "SegmentGap", 0.3f,
                "Pause in seconds between a line's segments (narrator -> character swap). 0 = instant.");
            CfgBorderless = Config.Bind("Display", "BorderlessFullscreen", false,
                "Force borderless fullscreen at desktop resolution on startup.");
            CfgLogLines = Config.Bind("Debug", "LogLines", true,
                "Log each played / missed dialogue node key to the BepInEx log.");

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
            if (Pack != null) Player.SetRoot(Pack.Root);

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

            if (CfgBorderless.Value)
            {
                try { BorderlessWindow.Apply(); Log.LogInfo("Borderless fullscreen applied."); }
                catch (Exception e) { Log.LogWarning("Borderless fullscreen failed: " + e.Message); }
            }

            Log.LogInfo("SRR AI Voices ready.");
        }
    }
}
