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
        public static ConfigEntry<float> CfgVolume;
        public static ConfigEntry<float> CfgSegmentGap;
        public static ConfigEntry<bool> CfgBorderless;
        public static ConfigEntry<bool> CfgLogLines;

        public static VoicePack Pack;
        public static VoicePlayer Player;

        void Awake()
        {
            Instance = this;
            Log = Logger;

            CfgEnabled = Config.Bind("General", "Enabled", true, "Master enable for AI voices.");
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

            try
            {
                var harmony = new Harmony(GUID);
                harmony.PatchAll();
                Log.LogInfo("Harmony patches applied (ShowNodeText / StartConversation / EndConversation).");
            }
            catch (Exception e)
            {
                Log.LogError("Harmony PatchAll failed: " + e);
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
