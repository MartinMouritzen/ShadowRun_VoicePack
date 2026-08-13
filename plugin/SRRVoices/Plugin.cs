using System;
using System.IO;
using System.Reflection;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace SRRVoices
{
    [BepInPlugin(GUID, "SRR AI Voices", "1.9.0")]
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
        public static ConfigEntry<bool> CfgTraceLoad;
        public static ConfigEntry<bool> CfgFixLightHang;

        // Prefix on AssetBundleManager.LoadItemSync — logs what is being asked for BEFORE the call,
        // so the request that never returns is the last line in the log rather than missing from it.
        // Only installed when TraceSceneLoad is on.
        public static void TraceLoadItem(string bundle, string item)
        {
            try { if (Log != null) Log.LogInfo("LoadItemSync <- " + item + "   [" + bundle + "]"); }
            catch (Exception) { }
        }

        // First-hit only: these run in loops (addSharedPortrait once per character), and all we need
        // is which of them the load reached, not how often.
        static readonly System.Collections.Generic.Dictionary<string, bool> stepSeen
            = new System.Collections.Generic.Dictionary<string, bool>();
        public static void TraceStep(MethodBase __originalMethod)
        {
            try
            {
                if (Log == null || __originalMethod == null) return;
                string n = __originalMethod.DeclaringType.Name + "." + __originalMethod.Name;
                if (stepSeen.ContainsKey(n)) return;
                stepSeen[n] = true;
                Log.LogWarning("STEP REACHED: " + n + "   (props so far: " + propTrace + ")");
            }
            catch (Exception) { }
        }

        // Prefix on SceneLoader.createProp, throttled. Logging every prop drowns the log and loses
        // the tail that matters when the game is killed mid-hang — and per-prop identity turned out
        // to be the wrong question anyway: a big scene legitimately has thousands (a1_hotel_s1's map
        // declares 5,927), so what tells you anything is the COUNT and whether it stops climbing.
        // Pair it with TraceStep: props still climbing = stuck in the loop, no steps reached = never
        // left it.
        internal static int propTrace = 0;
        public static void TraceCreateProp()
        {
            try
            {
                propTrace++;
                if (Log != null && propTrace % 100 == 0) Log.LogInfo("createProp count: " + propTrace);
            }
            catch (Exception) { }
        }
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
            CfgBorderless = Config.Bind("Display", "BorderlessFullscreen", true,
                "Run the game as a borderless window covering the monitor, instead of Unity's exclusive "
                + "fullscreen (which minimizes the game whenever it loses focus). Set false to leave the "
                + "window alone and use the game's own Fullscreen setting.");
            CfgPortraits = Config.Bind("General", "AIPortraits", true,
                "Show AI-generated portraits for characters the game ships without one. "
                + "Characters with their own portrait art are never changed.");
            CfgLogLines = Config.Bind("Debug", "LogLines", true,
                "Log each played / missed dialogue node key to the BepInEx log.");
            CfgFixLightHang = Config.Bind("General", "FixLightScriptLoadHang", true,
                "Work around a VANILLA bug that can make a save permanently unloadable: restoring a "
                + "prop whose light animation started long ago spins forever in a float32 rounding "
                + "cliff, mid scene-load. Leave on; it only touches jumps of 1000s or more.");
            CfgTraceLoad = Config.Bind("Debug", "TraceSceneLoad", false,
                "Diagnostic for a scene that never finishes loading. Switches on the GAME'S OWN load "
                + "instrumentation (Settings.WatchPerf/WatchMem, all Logger channels) and logs every "
                + "asset AssetBundleManager.LoadItemSync is asked for, so the last line before the "
                + "silence names the step that stalled. Very chatty — leave off unless diagnosing.");
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

            // The engine's own help-screen tutorials. A separate family from the floating text
            // above: those are authored in scenes, these come out of the UI string table and had
            // no hook at all, so they had never been voiced.
            try
            {
                var post = new HarmonyMethod(typeof(Patch_HelpScreen).GetMethod("Postfix"));
                var methods = Patch_HelpScreen.FindAll();
                int n = 0;
                foreach (var m in methods)
                {
                    try { harmony.CreateProcessor(m).AddPostfix(post).Patch(); n++; }
                    catch (Exception e) { Log.LogWarning("help patch skip " + m.DeclaringType.Name + "." + m.Name + ": " + e.Message); }
                }
                if (n > 0) Log.LogInfo("Patched " + n + "/" + methods.Count + " help-screen methods (tutorials).");
                else Log.LogWarning("No help-screen method found — tutorial popups stay unvoiced.");
            }
            catch (Exception e)
            {
                Log.LogWarning("Help-screen patch setup failed: " + e.Message);
            }

            // Vanilla bugfix, on by default: a save with animated lights can hang the scene load
            // forever (float32 precision cliff in PropLightComponent — see Patch_LightScriptPhase).
            // Isolated, because a missing type here must not cost anyone their voices.
            if (CfgFixLightHang == null || CfgFixLightHang.Value)
            {
                try
                {
                    var plc = typeof(ConversationManager).Assembly.GetType("PropLightComponent");
                    var ult = (plc == null) ? null : HarmonyLib.AccessTools.Method(
                        plc, "UpdateLightTransition", new Type[] { typeof(float) }, null);
                    if (ult != null)
                    {
                        harmony.CreateProcessor(ult)
                               .AddPrefix(new HarmonyMethod(typeof(Patch_LightScriptPhase).GetMethod("Prefix")))
                               .Patch();
                        Log.LogInfo("Light-script phase fix installed (PropLightComponent.UpdateLightTransition).");
                    }
                    else Log.LogWarning("PropLightComponent.UpdateLightTransition not found — the "
                                        + "vanilla animated-light load hang is NOT patched.");
                }
                catch (Exception e)
                {
                    Log.LogWarning("Light-script phase fix failed: " + e.Message);
                }
            }

            // Scene-load tracing (off by default). A save made inside a mission scene restores a
            // multi-megabyte .srt scene blob, and one of Martin's hung there forever — with the
            // plugin removed entirely, so it is not ours. Rather than invent instrumentation, switch
            // on the one the game already ships: Settings.WatchPerf logs each load stage's elapsed
            // time, WatchMem logs the GC heap after each, and the Logger's Unity channel filter is a
            // plain int bitmask, so opening it up routes every LogChannel.LOAD line into
            // output_log.txt. Warn/Error already bypass that filter, which is why "Could not find X,
            // creating temp atlas" would have shown regardless.
            if (CfgTraceLoad != null && CfgTraceLoad.Value)
            {
                try
                {
                    var asm = typeof(ConversationManager).Assembly;
                    var settings = asm.GetType("Settings");
                    var logger = asm.GetType("Logger");
                    int on = 0;
                    if (settings != null)
                    {
                        foreach (string fn in new string[] { "WatchPerf", "WatchMem" })
                        {
                            var f = HarmonyLib.AccessTools.Field(settings, fn);
                            if (f != null) { f.SetValue(null, true); on++; }
                        }
                        var filter = HarmonyLib.AccessTools.Field(settings, "UnityLogFilter");
                        if (filter != null) { filter.SetValue(null, -1); on++; }   // every channel
                    }
                    if (logger != null)
                    {
                        var upd = HarmonyLib.AccessTools.Method(logger, "UpdateFilters", null, null);
                        if (upd != null) { upd.Invoke(null, null); on++; }
                    }
                    Log.LogWarning("TraceSceneLoad ON — game load instrumentation enabled (" + on
                                   + "/4 switches). Expect a very chatty log.");

                    // Asset-level granularity: the game's stage logging is coarse, and a stall inside
                    // one asset load would sit between two stage marks with nothing to name it.
                    // The PRIVATE (string bundle, string item, Type) overload, not the public FQAN
                    // one: the public overload resolves the bundle and delegates here, so patching
                    // the inner method catches both call paths with one hook. Named explicitly
                    // because AccessTools cannot pick between the overloads on name alone.
                    var abm = asm.GetType("AssetBundleManager");
                    var li = (abm == null) ? null : HarmonyLib.AccessTools.Method(
                        abm, "LoadItemSync",
                        new Type[] { typeof(string), typeof(string), typeof(Type) }, null);
                    if (li != null)
                    {
                        harmony.CreateProcessor(li)
                               .AddPrefix(new HarmonyMethod(typeof(Plugin).GetMethod("TraceLoadItem")))
                               .Patch();
                        Log.LogInfo("TraceSceneLoad: AssetBundleManager.LoadItemSync traced.");
                    }
                    else Log.LogWarning("TraceSceneLoad: AssetBundleManager.LoadItemSync not found.");

                    // Prop-level granularity. The first trace proved the atlas phase COMPLETES
                    // ("Atlases created for 778 prop(s): 5792ms", heap only 57 MB) and that the
                    // engine is still alive afterwards — an analytics coroutine kept logging — so it
                    // is the load coroutine itself that stops, in the createProp loop that runs right
                    // after. There is no per-prop logging in the game, so name each prop before it is
                    // built and the last line is the one that never finished.
                    var slt = asm.GetType("SceneLoader");
                    var cp = (slt == null) ? null : HarmonyLib.AccessTools.Method(slt, "createProp", null, null);
                    if (cp != null)
                    {
                        harmony.CreateProcessor(cp)
                               .AddPrefix(new HarmonyMethod(typeof(Plugin).GetMethod("TraceCreateProp")))
                               .Patch();
                        Log.LogInfo("TraceSceneLoad: SceneLoader.createProp traced.");
                    }
                    else Log.LogWarning("TraceSceneLoad: SceneLoader.createProp not found.");

                    // Bracket the window the game's own logging leaves dark. Its last line is
                    // "After Atlases current GC Heap" and the next is "Props and meshes created",
                    // and everything between them — factions, variables, scratchpad, map events,
                    // sense tags, goals, patrol routes, regions, portrait map — logs nothing at all.
                    // Those are all ordinary named methods, so one hook each, logged the FIRST time
                    // each is reached, turns that dark stretch into a progress trail without flooding
                    // the log. The last name printed is how far the load got.
                    //
                    // StopwatchUnity.Mark would have been neater (it names the stages itself) but
                    // Harmony cannot rewrite it — "IL Compile Error" — so this does the same job the
                    // long way round.
                    string[][] steps = {
                        new string[] { "RunManager", "AddDisguises" },
                        new string[] { "Faction", "Initialize" },
                        new string[] { "RunManager", "addVariable" },
                        new string[] { "RunManager", "addUserEvents" },
                        new string[] { "RunManager", "addUserSenseTags" },
                        new string[] { "RunManager", "addGoal" },
                        new string[] { "SceneLoader", "createPatrolRoute" },
                        new string[] { "SceneLoader", "createRegion" },
                        new string[] { "RunManager", "InitializePortraitMap" },
                        new string[] { "RunManager", "SetScenePortraitMap" },
                        new string[] { "RunManager", "addSharedPortrait" },
                        new string[] { "RunManager", "AddSharedPortraitsFromCurrentParty" },
                        new string[] { "RunManager", "createSharedPortraitAtlases" },
                        new string[] { "SceneLoader", "ResourceUnloadCheck" },
                    };
                    var stepPre = new HarmonyMethod(typeof(Plugin).GetMethod("TraceStep"));
                    int steps_ok = 0;
                    foreach (string[] s in steps)
                    {
                        try
                        {
                            var st2 = asm.GetType(s[0]);
                            var m2 = (st2 == null) ? null : HarmonyLib.AccessTools.Method(st2, s[1], null, null);
                            if (m2 == null) { Log.LogWarning("TraceSceneLoad: " + s[0] + "." + s[1] + " not found."); continue; }
                            harmony.CreateProcessor(m2).AddPrefix(stepPre).Patch();
                            steps_ok++;
                        }
                        catch (Exception se)
                        {
                            Log.LogWarning("TraceSceneLoad: " + s[0] + "." + s[1] + " skip: " + se.Message);
                        }
                    }
                    Log.LogInfo("TraceSceneLoad: " + steps_ok + "/" + steps.Length + " post-props steps traced.");
                }
                catch (Exception e)
                {
                    Log.LogWarning("TraceSceneLoad setup failed: " + e.Message);
                }
            }

            // Stop popup narration when the popup is dismissed (isolated: one seam for every popup
            // family, since HelpScreenPopup, the character-creation panels and the scene
            // "Display Text In Popup" action all build a FullscreenPopup).
            try
            {
                var fpType = typeof(ConversationManager).Assembly.GetType("FullscreenPopup");
                var destroyM = (fpType == null) ? null
                             : HarmonyLib.AccessTools.Method(fpType, "DestroyPopup", null, null);
                if (destroyM != null)
                {
                    harmony.CreateProcessor(destroyM)
                           .AddPostfix(new HarmonyMethod(typeof(Patch_PopupClose).GetMethod("ClosePostfix")))
                           .Patch();
                    Log.LogInfo("Popup close hook installed (FullscreenPopup.DestroyPopup).");
                }
                else Log.LogWarning("FullscreenPopup.DestroyPopup not found — popup narration will "
                                    + "keep playing after the popup is dismissed.");
            }
            catch (Exception e)
            {
                Log.LogWarning("Popup close patch failed: " + e.Message);
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

            // End-of-campaign epilogue narration (isolated: the screen may differ in sequels).
            // Hooked on EpilogueScreen.Initialize rather than PDA.ShowEpilogueScreen because the
            // latter builds the screen through an iterator and returns before the text exists.
            try
            {
                var epType = typeof(ConversationManager).Assembly.GetType("EpilogueScreen");
                var epInit = (epType == null) ? null : HarmonyLib.AccessTools.Method(epType, "Initialize", null, null);
                if (epInit != null)
                {
                    harmony.CreateProcessor(epInit)
                           .AddPostfix(new HarmonyMethod(typeof(Patch_Epilogue).GetMethod("InitPostfix")))
                           .Patch();
                    Log.LogInfo("Epilogue narration hook installed (EpilogueScreen.Initialize).");
                }
                else Log.LogWarning("EpilogueScreen.Initialize not found — the epilogue stays unvoiced.");

                var epClose = new HarmonyMethod(typeof(Patch_Epilogue).GetMethod("ClosePostfix"));
                int epHooks = 0;
                if (epType != null)
                {
                    var m = HarmonyLib.AccessTools.Method(epType, "Uninitialize", null, null);
                    if (m != null)
                    {
                        try { harmony.CreateProcessor(m).AddPostfix(epClose).Patch(); epHooks++; }
                        catch (Exception e) { Log.LogWarning("epilogue close patch skip: " + e.Message); }
                    }
                }
                var pdaT = typeof(ConversationManager).Assembly.GetType("PDA");
                var pdaClose = (pdaT == null) ? null : HarmonyLib.AccessTools.Method(pdaT, "CloseEpilogueScreen", null, null);
                if (pdaClose != null)
                {
                    try { harmony.CreateProcessor(pdaClose).AddPostfix(epClose).Patch(); epHooks++; }
                    catch (Exception e) { Log.LogWarning("epilogue close patch skip (PDA): " + e.Message); }
                }
                Log.LogInfo("Epilogue close hooks installed on " + epHooks + " method(s).");
            }
            catch (Exception e)
            {
                Log.LogWarning("Epilogue patch failed: " + e.Message);
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

            // Started unconditionally: the watchdog reads the setting every tick, so the in-game
            // toggle takes effect (both ways) without a restart.
            try { StartCoroutine(BorderlessWindow.Watch()); }
            catch (Exception e) { Log.LogWarning("Borderless fullscreen unavailable: " + e.Message); }

            Log.LogInfo("SRR AI Voices ready.");
        }
    }
}
