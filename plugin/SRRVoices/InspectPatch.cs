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
            if (!__result || Plugin.Pack == null || Plugin.Player == null || __instance == null) return;
            try
            {
                InteractionBehaviorRoot data = __instance.interactionData;
                if (data == null || data.inspectInteraction == null) return;
                string raw = data.inspectInteraction.inspectText;
                if (string.IsNullOrEmpty(raw)) return;
                string key = "insp_" + Md5Hex16(raw);
                string[] clips;
                if (Plugin.Pack.TryGet(key, out clips))
                {
                    if (Plugin.CfgLogLines != null && Plugin.CfgLogLines.Value)
                        Plugin.Log.LogInfo("play inspect " + key + " (" + clips.Length + " clips)");
                    Plugin.Player.PlaySequence(clips);
                }
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("inspect hook: " + e.Message);
            }
        }

        // Must match Python: hashlib.md5(text.encode('utf-8')).hexdigest()[:16]
        static string Md5Hex16(string s)
        {
            MD5 md5 = MD5.Create();
            byte[] h = md5.ComputeHash(Encoding.UTF8.GetBytes(s));
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < h.Length; i++) sb.Append(h[i].ToString("x2"));
            return sb.ToString().Substring(0, 16);
        }
    }
}
