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

            // Phantom/sentinel nodes (index < 0) fire immediately AFTER the first real node when a
            // conversation opens. Their "no VO" branch would stop playback and cut off the first
            // node's audio a frame after it started (which is exactly why the opening line was silent
            // on first display but played on navigate-back). Ignore them entirely.
            if (node.index < 0) return;

            Conversation convo = ConvoField != null ? ConvoField.GetValue(__instance) as Conversation : null;
            if (convo == null && Patch_StartConversation.LastConvo != null)
                convo = Patch_StartConversation.LastConvo;      // fallback if field read fails
            if (convo == null || convo.idRef == null) return;

            string key = convo.idRef.id + "_" + node.index;
            string[] clips;
            // Variants first: a line that says $(l.race) has a clip per metatype. Falls back to the
            // generic clip when this line does not vary, or when that variant was never generated.
            if (Variants.TryGet(Plugin.Pack, key, out clips))
            {
                if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value)
                    Plugin.Log.LogInfo("play " + key + " (" + clips.Length + " clips)");
                Plugin.Player.PlaySequence(clips);
            }
            else
            {
                if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value)
                    Plugin.Log.LogInfo("no VO " + key);
                // A popup on screen outranks the conversation underneath it (see
                // Patch_PopupClose.OwnsCurrentNarration): silence here means this NODE has no
                // clip, not that the modal narration should stop.
                if (!Patch_PopupClose.OwnsCurrentNarration())
                    Plugin.Player.StopVoice("node has no VO");
            }
        }
    }

    // Which conversation is "in play" right now, for gated barks (see VoicePack.TryGetGate).
    public static class ConvoGate
    {
        public static string LastEnded;    // idRef.id of the conversation that most recently ended

        public static string CurrentId()
        {
            Conversation c = Patch_StartConversation.LastConvo;
            return (c != null && c.idRef != null) ? c.idRef.id : null;
        }

        // Both the running conversation and the one that just ended are accepted, deliberately.
        // A gated bark is drawn by a scene trigger reacting to "On Conversation Complete", and
        // whether ConversationManager.EndConversation has already run by that point decides which
        // of the two holds the id — an ordering inside the engine that we would otherwise have to
        // guess at. Testing both is correct under either order, and the log line records which one
        // matched, so a real playthrough settles it without another build.
        public static bool Allows(string[] wanted)
        {
            if (wanted == null || wanted.Length == 0) return true;
            string cur = CurrentId(), last = LastEnded;
            for (int i = 0; i < wanted.Length; i++)
                if (wanted[i] == cur || wanted[i] == last) return true;
            return false;
        }

        public static string Describe()
        {
            return "current=" + (CurrentId() ?? "-") + " lastEnded=" + (LastEnded ?? "-");
        }
    }

    [HarmonyPatch(typeof(ConversationManager), "EndConversation")]
    public static class Patch_EndConversation
    {
        static void Postfix()
        {
            // Remember what just ended BEFORE LastConvo is cleared below — a bark gated on this
            // conversation may be drawn a moment from now by a scene trigger.
            ConvoGate.LastEnded = ConvoGate.CurrentId();

            // StopVoice, not a full stop: a bark can fire from the same click that closes the
            // conversation (the Haven pet-the-dog trigger draws "Woof!" and ends the convo together),
            // and it is still streaming its clip when we get here. The old StopAll cancelled it every time.
            //
            // ...and the same click can also OPEN a narrated popup, which lands on the main channel
            // and is therefore not saved by that. Confirming a mission ends the travel conversation
            // and raises the Hired Runners popup in one beat; this ran a frame after the popup
            // dispatched its narration and killed it while the clip was still downloading. So the
            // popup's own playback is exempt — it is modal, and it stops when the popup closes.
            if (Plugin.Player != null && !Patch_PopupClose.OwnsCurrentNarration())
                Plugin.Player.StopVoice("conversation ended");
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
