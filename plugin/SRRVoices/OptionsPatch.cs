using System;
using HarmonyLib;
using UnityEngine;

namespace SRRVoices
{
    // Injects "Voice Volume" and "Voice Speed" slider rows into the game's own Options screen
    // (audio section), cloned from the existing "Sound Volume" row so they inherit the exact
    // NGUI look. OptionsScreen fields: <name>VolumeText (UILabel), <name>VolumeSlider (UISlider),
    // plus BG/FG/Thumb sprites; sliders dispatch via NGUI 2.x eventReceiver+functionName
    // (SendMessage with a float). Patched manually (isolated) from Plugin.Awake.
    public static class Patch_Options
    {
        const string MARKER = "SRRVoicesOptionsRows";

        public static void Postfix(object __instance)
        {
            try
            {
                if (Plugin.CfgEnabled == null || !Plugin.CfgEnabled.Value) return;
                MonoBehaviour screen = __instance as MonoBehaviour;
                if (screen == null) return;
                Component soundSlider = GetComp(screen, "soundVolumeSlider");
                Component soundText = GetComp(screen, "soundVolumeText");
                Component ambientSlider = GetComp(screen, "ambientVolumeSlider");
                Component ambientText = GetComp(screen, "ambientVolumeText");
                if (soundSlider == null || soundText == null || ambientSlider == null || ambientText == null) return;
                Transform parent = soundSlider.transform.parent;
                if (parent == null) return;
                if (parent.Find(MARKER) != null) return;   // options screen re-initialized; rows already exist

                // one row's worth of vertical offset, measured from the game's own layout
                Vector3 dText = soundText.transform.localPosition - ambientText.transform.localPosition;
                Vector3 dSlider = soundSlider.transform.localPosition - ambientSlider.transform.localPosition;

                GameObject holder = new GameObject(MARKER);
                holder.transform.parent = parent;
                holder.transform.localPosition = Vector3.zero;
                holder.transform.localScale = Vector3.one;
                OptionsRowsHandler handler = holder.AddComponent<OptionsRowsHandler>();

                handler.volLabel = CloneLabel(soundText, dText, "Voice Volume");
                Component volSlider = CloneSlider(soundSlider, dSlider, holder, "OnVoiceVolumeSliderChange");
                SetSliderValue(volSlider, (Plugin.CfgVolume != null) ? Mathf.Clamp01(Plugin.CfgVolume.Value) : 1f);

                handler.spdLabel = CloneLabel(soundText, dText * 2f, "Voice Speed");
                Component spdSlider = CloneSlider(soundSlider, dSlider * 2f, holder, "OnVoiceSpeedSliderChange");
                SetSliderValue(spdSlider, SpeedToSlider((Plugin.CfgSpeed != null) ? Plugin.CfgSpeed.Value : 1f));
                handler.UpdateSpeedLabel();

                // grow the audio panel background to make room for the two extra rows
                Component bg = GetComp(screen, "audioBG");
                if (bg != null)
                {
                    Vector3 s = bg.transform.localScale;
                    float grow = Mathf.Abs(dText.y) * 2f;
                    bg.transform.localScale = new Vector3(s.x, s.y + grow, s.z);
                    // extend toward wherever the new rows went (rows stack in the dText direction)
                    bg.transform.localPosition += new Vector3(0f, Mathf.Sign(dText.y) * grow / 2f, 0f);
                }
                if (Plugin.Log != null) Plugin.Log.LogInfo("Options screen: voice volume/speed rows injected.");
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("options inject: " + e.Message);
            }
        }

        static Component GetComp(MonoBehaviour screen, string field)
        {
            var f = AccessTools.Field(screen.GetType(), field);
            return (f == null) ? null : f.GetValue(screen) as Component;
        }

        static Component CloneLabel(Component srcLabel, Vector3 offset, string caption)
        {
            GameObject go = UnityEngine.Object.Instantiate(srcLabel.gameObject) as GameObject;
            go.name = "SRRVoices_" + caption.Replace(" ", "");
            go.transform.parent = srcLabel.transform.parent;
            go.transform.localScale = srcLabel.transform.localScale;
            go.transform.localRotation = srcLabel.transform.localRotation;
            go.transform.localPosition = srcLabel.transform.localPosition + offset;
            Component loc = go.GetComponent("UILocalize");           // would overwrite our caption
            if (loc != null) UnityEngine.Object.Destroy(loc);
            Component lbl = go.GetComponent("UILabel");
            SetProp(lbl, "text", caption);
            return lbl;
        }

        static Component CloneSlider(Component srcSlider, Vector3 offset, GameObject receiver, string callback)
        {
            GameObject go = UnityEngine.Object.Instantiate(srcSlider.gameObject) as GameObject;
            go.name = "SRRVoices_" + callback;
            go.transform.parent = srcSlider.transform.parent;
            go.transform.localScale = srcSlider.transform.localScale;
            go.transform.localRotation = srcSlider.transform.localRotation;
            go.transform.localPosition = srcSlider.transform.localPosition + offset;
            Component slider = go.GetComponent("UISlider");
            if (slider != null)
            {
                // If the original slider's foreground/thumb live OUTSIDE its own hierarchy, the
                // clone still points at the originals; there is nothing sane to show then, so log it.
                var fgF = AccessTools.Field(slider.GetType(), "foreground");
                Transform fg = fgF == null ? null : fgF.GetValue(slider) as Transform;
                if (fg != null && !fg.IsChildOf(go.transform) && Plugin.Log != null)
                    Plugin.Log.LogWarning("options inject: slider foreground is external; visuals may not track.");
                var recvF = AccessTools.Field(slider.GetType(), "eventReceiver");
                if (recvF != null) recvF.SetValue(slider, receiver);
                var fnF = AccessTools.Field(slider.GetType(), "functionName");
                if (fnF != null) fnF.SetValue(slider, callback);
            }
            return slider;
        }

        internal static void SetSliderValue(Component slider, float v)
        {
            if (slider != null) SetProp(slider, "sliderValue", v);
        }

        static void SetProp(Component c, string prop, object val)
        {
            if (c == null) return;
            var p = AccessTools.Property(c.GetType(), prop);
            if (p != null) p.SetValue(c, val, null);
        }

        internal static float SpeedToSlider(float speed) { return Mathf.Clamp01((speed - 0.5f) / 1.5f); }
        internal static float SliderToSpeed(float v) { return 0.5f + Mathf.Clamp01(v) * 1.5f; }
    }

    // Receives the NGUI SendMessage callbacks from the injected sliders.
    public class OptionsRowsHandler : MonoBehaviour
    {
        public Component volLabel;
        public Component spdLabel;

        public void OnVoiceVolumeSliderChange(float v)
        {
            if (Plugin.CfgVolume != null) Plugin.CfgVolume.Value = Mathf.Clamp01(v);
            if (Plugin.Player != null) Plugin.Player.ApplyLive();
        }

        public void OnVoiceSpeedSliderChange(float v)
        {
            if (Plugin.CfgSpeed != null)
                Plugin.CfgSpeed.Value = Mathf.Round(Patch_Options.SliderToSpeed(v) * 100f) / 100f;
            UpdateSpeedLabel();
            if (Plugin.Player != null) Plugin.Player.ApplyLive();
        }

        public void UpdateSpeedLabel()
        {
            if (spdLabel == null || Plugin.CfgSpeed == null) return;
            var p = HarmonyLib.AccessTools.Property(spdLabel.GetType(), "text");
            if (p != null) p.SetValue(spdLabel, "Voice Speed  " + Plugin.CfgSpeed.Value.ToString("0.00") + "x", null);
        }
    }
}
