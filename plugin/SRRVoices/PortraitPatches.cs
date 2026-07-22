using System;
using System.Collections.Generic;
using System.IO;
using HarmonyLib;
using UnityEngine;
using isogame;

namespace SRRVoices
{
    // Optional AI portraits for characters the game ships without one.
    //
    // This rides the game's OWN portrait pipeline rather than poking at the dialogue UI:
    //   Player.portraitName -> RunManager.getPortraitHelper -> tryCreatePortraitAtlas
    //     -> FileLoader.LoadTexture("portraits", <name>)  -> art/portraits/<name>.png
    // So we only have to do two things: give a speaker a portrait NAME we own, and answer the
    // texture load for that name from our own folder. The engine then builds the atlas, the
    // thumbnail and the frame exactly as it does for shipped portraits — no UI surgery, and it
    // works in every place a portrait is drawn (dialogue, response rows, anywhere else).
    //
    // portraits/portraits.index maps "<normalised actor name>\t<file.png>".
    public static class PortraitPatches
    {
        const string PREFIX = "srrv_";          // portrait names we own

        static readonly Dictionary<string, string> ByActor =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);   // actor -> file
        static readonly Dictionary<string, string> ByPortraitName =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);   // srrv_x -> file
        static readonly Dictionary<string, string> ByConv =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);   // convGuid -> srrv_ name
        static string root;

        public static int Count { get { return ByActor.Count; } }

        // True only when a portrait pack actually loaded. Used to hide the in-game AI-portraits
        // toggle in builds that ship no pack, so there's no dead switch.
        public static bool Available { get { return ByActor.Count > 0 || ByConv.Count > 0; } }

        public static string Norm(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            var sb = new System.Text.StringBuilder(s.Length);
            foreach (char ch in s)
                if (char.IsLetterOrDigit(ch)) sb.Append(char.ToLowerInvariant(ch));
            return sb.ToString();
        }

        public static void Load(string dir)
        {
            root = dir;
            string idx = Path.Combine(dir, "portraits.index");
            if (!File.Exists(idx))
            {
                if (Plugin.Log != null) Plugin.Log.LogInfo("no portraits.index — AI portraits unavailable.");
                return;
            }
            foreach (string raw in File.ReadAllLines(idx))
            {
                if (raw.Length == 0 || raw[0] == '#') continue;
                string[] p = raw.Split('\t');
                if (p.Length < 2) continue;
                string col0 = p[0].Trim(), file = p[1].Trim();
                if (col0.StartsWith("conv:"))
                {
                    // conv:<guid> -> a portrait NAME we own; the file is served by name below.
                    string guid = col0.Substring(5);
                    string pname = PREFIX + "c" + guid;
                    ByConv[guid] = pname;
                    ByPortraitName[pname] = file;
                }
                else
                {
                    ByActor[col0] = file;
                    ByPortraitName[PREFIX + col0] = file;
                }
            }
            if (Plugin.Log != null)
                Plugin.Log.LogInfo("AI portraits: " + ByActor.Count + " characters, "
                    + ByConv.Count + " conversation keys mapped.");
        }

        public static void Apply(Harmony harmony)
        {
            if (ByActor.Count == 0 && ByConv.Count == 0) return;
            var asm = typeof(ConversationManager).Assembly;

            // 1) answer texture loads for the portrait names we own
            int hooked = 0;
            foreach (Type t in asm.GetTypes())
            {
                if (t.Name != "ProjectInfo" && t.Name != "FileLoader") continue;
                foreach (var m in t.GetMethods(AccessTools.all))
                {
                    if (m.Name != "LoadTexture") continue;
                    var ps = m.GetParameters();
                    if (ps.Length != 3 || ps[0].ParameterType != typeof(string)
                        || ps[1].ParameterType != typeof(string)) continue;
                    try
                    {
                        harmony.CreateProcessor(m)
                               .AddPrefix(new HarmonyMethod(typeof(PortraitPatches).GetMethod("LoadTexturePrefix")))
                               .Patch();
                        hooked++;
                    }
                    catch (Exception e)
                    {
                        if (Plugin.Log != null) Plugin.Log.LogWarning("portrait texture hook: " + e.Message);
                    }
                }
            }
            if (hooked == 0)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("no LoadTexture found — AI portraits disabled.");
                return;
            }

            // 2) a portrait name we own must survive the game's "is this a known portrait?" check
            var rm = asm.GetType("RunManager");
            var final = (rm == null) ? null : AccessTools.Method(rm, "GetFinalPortraitName", new Type[] { typeof(string) }, null);
            if (final != null)
                harmony.CreateProcessor(final)
                       .AddPostfix(new HarmonyMethod(typeof(PortraitPatches).GetMethod("FinalNamePostfix")))
                       .Patch();

            // 3a) the precise path: ShowNodeText knows the node and (via thisConvoDef) the
            //     conversation, so set the SPEAKER's portrait name keyed on the conversation GUID
            //     — robust to the actorName differing from the lab's conversation-derived name.
            _convoField = AccessTools.Field(typeof(ConversationManager), "thisConvoDef");
            foreach (var m in typeof(ConversationManager).GetMethods(AccessTools.all))
            {
                if (m.Name != "ShowNodeText") continue;
                try
                {
                    harmony.CreateProcessor(m)
                           .AddPrefix(new HarmonyMethod(typeof(PortraitPatches).GetMethod("NodePrefix")))
                           .Patch();
                }
                catch (Exception e)
                {
                    if (Plugin.Log != null) Plugin.Log.LogWarning("portrait node hook: " + e.Message);
                }
            }

            // 3b) fallback path for anything not resolved above (barks, response rows): fill in
            //     by scene actorName. Only touches speakers the game leaves blank.
            foreach (string name in new string[] { "ShowNodeText", "ShowResponse" })
            {
                foreach (var m in typeof(ConversationManager).GetMethods(AccessTools.all))
                {
                    if (m.Name != name) continue;
                    bool hasPlayer = false;
                    foreach (var pp in m.GetParameters())
                        if (pp.ParameterType.Name == "Player") hasPlayer = true;
                    if (!hasPlayer) continue;
                    try
                    {
                        harmony.CreateProcessor(m)
                               .AddPrefix(new HarmonyMethod(typeof(PortraitPatches).GetMethod("SpeakerPrefix")))
                               .AddPostfix(new HarmonyMethod(typeof(PortraitPatches).GetMethod("LogSpeaker")))
                               .Patch();
                    }
                    catch (Exception e)
                    {
                        if (Plugin.Log != null) Plugin.Log.LogWarning("portrait speaker hook " + name + ": " + e.Message);
                    }
                }
            }
            if (Plugin.Log != null) Plugin.Log.LogInfo("AI portrait hooks installed (native portrait pipeline).");
        }

        static System.Reflection.FieldInfo _convoField;

        static bool Replaceable(string portraitName)
        {
            return string.IsNullOrEmpty(portraitName)
                || portraitName == RunManager.FALLBACK_PORTRAIT_NAME
                || portraitName.StartsWith(PREFIX);
        }

        // Precise assignment: keyed on the conversation GUID, placed on the exact Player that
        // ShowNodeText will resolve as the speaker. Mirrors the game's own resolution (by
        // node.sourceInSceneRef, then by tag) so we set the field on the right actor before the
        // original method reads it. Only fills a portrait the game leaves blank.
        public static void NodePrefix(ConversationNode node, Player thisSpeaker, ConversationManager __instance)
        {
            if (Plugin.CfgPortraits == null || !Plugin.CfgPortraits.Value) return;
            if (node == null || ByConv.Count == 0) return;
            try
            {
                Conversation convo = (_convoField != null) ? _convoField.GetValue(__instance) as Conversation : null;
                if (convo == null) convo = Patch_StartConversation.LastConvo;
                if (convo == null || convo.idRef == null) return;
                string pname;
                if (!ByConv.TryGetValue(convo.idRef.id, out pname)) return;

                Player speaker = thisSpeaker;
                var rm = RunManager.Instance;
                if (rm != null && rm.grid != null && rm.grid.allPlayers != null)
                {
                    if (node.sourceInSceneRef != null)
                    {
                        foreach (Player p in rm.grid.allPlayers)
                            if (p != null && p.getIdRef().id == node.sourceInSceneRef.id) { speaker = p; break; }
                    }
                    else if (!string.IsNullOrEmpty(node.sourceWithTagInScene))
                    {
                        foreach (Player p in rm.grid.allPlayers)
                        {
                            if (p == null || p.generalTags == null) continue;
                            bool hit = false;
                            foreach (string tag in p.generalTags)
                                if (tag == node.sourceWithTagInScene) { hit = true; break; }
                            if (hit) { speaker = p; break; }
                        }
                    }
                }
                if (speaker == null || !Replaceable(speaker.portraitName)) return;
                if (speaker.portraitName == pname) return;
                speaker.portraitName = pname;
                if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value && Plugin.Log != null)
                    Plugin.Log.LogInfo("portrait(conv): '" + speaker.actorName + "' <- " + pname
                        + " (conv " + convo.idRef.id + ")");
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("portrait node prefix: " + e.Message);
            }
        }

        // Give speakers one of our portraits when the game has none of its own for them.
        //
        // ShowNodeText REASSIGNS its thisSpeaker parameter from the scene grid before reading
        // portraitName, so patching the incoming argument changes an object the method then
        // discards. Instead every Player in the scene is fixed up, so whichever instance the
        // method settles on already carries our name.
        static float _lastFixup = -999f;

        public static void SpeakerPrefix()
        {
            if (Plugin.CfgPortraits == null || !Plugin.CfgPortraits.Value) return;
            if (Time.realtimeSinceStartup - _lastFixup < 0.5f) return;   // once per exchange, not per call
            _lastFixup = Time.realtimeSinceStartup;
            FixupScene();
        }

        public static void FixupScene()
        {
            try
            {
                var players = UnityEngine.Object.FindObjectsOfType(typeof(Player)) as Player[];
                if (players == null) return;
                int n = 0;
                foreach (Player p in players)
                {
                    if (p == null) continue;
                    string cur = p.portraitName;
                    // never replace a portrait the game already provides
                    if (!string.IsNullOrEmpty(cur)
                        && cur != RunManager.FALLBACK_PORTRAIT_NAME
                        && !cur.StartsWith(PREFIX)) continue;
                    string key = Norm(p.actorName);
                    string file;
                    if (!ByActor.TryGetValue(key, out file)) continue;
                    if (cur == PREFIX + key) continue;
                    p.portraitName = PREFIX + key;
                    n++;
                    if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value && Plugin.Log != null)
                        Plugin.Log.LogInfo("portrait: '" + p.actorName + "' -> " + file);
                }
                if (n > 0 && Plugin.Log != null && Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value)
                    Plugin.Log.LogInfo("portrait fixup: " + n + " actor(s) in this scene");
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("portrait fixup: " + e.Message);
            }
        }

        // Diagnostic: log every speaker the game shows, so a missing portrait can be traced to
        // the actual actorName rather than guessed at.
        public static void LogSpeaker(Player thisSpeaker)
        {
            if (Plugin.CfgLogLines == null || !Plugin.CfgLogLines.Value || Plugin.Log == null) return;
            try
            {
                if (thisSpeaker == null) { Plugin.Log.LogInfo("portrait: speaker=<null>"); return; }
                string key = Norm(thisSpeaker.actorName);
                Plugin.Log.LogInfo("portrait: speaker='" + thisSpeaker.actorName + "' key='" + key
                    + "' portraitName='" + thisSpeaker.portraitName + "' haveArt=" + ByActor.ContainsKey(key));
            }
            catch (Exception) { }
        }

        public static void FinalNamePostfix(string basePortraitName, ref string __result)
        {
            if (!string.IsNullOrEmpty(basePortraitName) && basePortraitName.StartsWith(PREFIX)
                && ByPortraitName.ContainsKey(basePortraitName))
                __result = basePortraitName;      // ours is valid even though the game never listed it
        }

        // Serve art/portraits/srrv_<x>.png from the plugin folder instead of the content pack.
        public static bool LoadTexturePrefix(string searchDirectory, string filename, ref Texture2D __result)
        {
            if (Plugin.CfgPortraits == null || !Plugin.CfgPortraits.Value) return true;
            try
            {
                if (searchDirectory != "portraits" || string.IsNullOrEmpty(filename)
                    || !filename.StartsWith(PREFIX)) return true;
                string file;
                if (!ByPortraitName.TryGetValue(filename, out file)) return true;
                string full = Path.Combine(root, file);
                if (!File.Exists(full)) return true;
                Texture2D tex = new Texture2D(0, 0);
                tex.LoadImage(File.ReadAllBytes(full));
                tex.filterMode = FilterMode.Bilinear;
                tex.mipMapBias = 0f;
                __result = tex;
                return false;                      // handled — skip the original
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("portrait load " + filename + ": " + e.Message);
                return true;
            }
        }
    }
}
