using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using isogame;

namespace SRRVoices
{
    // Play the matching clips when a dialogue node is displayed.
    // ConversationManager.ShowNodeText(ConversationNode node, Player thisSpeaker) is called once per
    // displayed node. Key = <thisConvoDef.idRef.id>_<node.index>.
    [HarmonyPatch(typeof(ConversationManager), "ShowNodeText")]
    public static class Patch_ShowNodeText
    {
        static readonly FieldInfo ConvoField =
            AccessTools.Field(typeof(ConversationManager), "thisConvoDef");

        static void Postfix(ConversationManager __instance, ConversationNode node)
        {
            if (Plugin.CfgEnabled == null || !Plugin.CfgEnabled.Value) return;
            if (Plugin.Pack == null || Plugin.Player == null || node == null) return;

            Conversation convo = ConvoField != null ? ConvoField.GetValue(__instance) as Conversation : null;
            if (convo == null && Patch_StartConversation.LastConvo != null)
                convo = Patch_StartConversation.LastConvo;      // fallback if field read fails
            if (convo == null || convo.idRef == null) return;

            string key = convo.idRef.id + "_" + node.index;
            string[] clips;
            if (Plugin.Pack.TryGet(key, out clips))
            {
                if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value)
                    Plugin.Log.LogInfo("play " + key + " (" + clips.Length + " clips)");
                Plugin.Player.PlaySequence(clips);
            }
            else
            {
                if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value)
                    Plugin.Log.LogInfo("no VO " + key);
                Plugin.Player.StopAll();
            }
        }
    }

    [HarmonyPatch(typeof(ConversationManager), "EndConversation")]
    public static class Patch_EndConversation
    {
        static void Postfix()
        {
            if (Plugin.Player != null) Plugin.Player.StopAll();
            Patch_StartConversation.LastConvo = null;
        }
    }

    // Preload the conversation's clips so per-node playback is instant.
    [HarmonyPatch(typeof(ConversationManager), "StartConversation")]
    public static class Patch_StartConversation
    {
        public static Conversation LastConvo;    // fallback source of the current convo id

        // Set the current convo BEFORE the method body runs. The game displays the first node
        // (calling ShowNodeText) during StartConversation, before thisConvoDef is readable and
        // before our Postfix would run — so without this the very first node of every conversation
        // couldn't be identified and played silently. The Prefix makes LastConvo available in time.
        static void Prefix(Conversation convoDef)
        {
            LastConvo = convoDef;
        }

        static void Postfix(Conversation convoDef)
        {
            LastConvo = convoDef;
            if (Plugin.CfgEnabled == null || !Plugin.CfgEnabled.Value) return;
            if (Plugin.Pack == null || Plugin.Player == null) return;
            if (convoDef == null || convoDef.idRef == null || convoDef.nodes == null) return;

            var keys = new List<string>();
            string cid = convoDef.idRef.id;
            var nodes = convoDef.nodes;
            for (int i = 0; i < nodes.Count; i++)
            {
                ConversationNode n = nodes[i];
                if (n != null) keys.Add(cid + "_" + n.index);
            }
            List<string> clips = Plugin.Pack.ClipsForKeys(keys);
            if (clips.Count > 0) Plugin.Player.Preload(clips);
        }
    }
}
