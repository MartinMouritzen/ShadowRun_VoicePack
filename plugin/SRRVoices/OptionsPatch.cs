using System;
using System.IO;
using BepInEx;
using HarmonyLib;
using UnityEngine;

namespace SRRVoices
{
    // Injects "Voice Volume" and "Voice Speed" slider rows into the game's own Options screen
    // (audio section), cloned from the existing "Sound Volume" row so they inherit the exact
    // NGUI look. OptionsScreen fields: <name>VolumeText (UILabel), <name>VolumeSlider (UISlider),
    // plus BG/FG/Thumb sprites; sliders dispatch via NGUI 2.x eventReceiver+functionName
    // (SendMessage with a float). Patched manually (isolated) from Plugin.Awake.
    //
    // Two layouts:
    //  - Main-menu OptionsScreen: rows appended inline below Sound Volume (there is room).
    //  - In-game Escape menu (PDAAnchor): the space below Sound Volume is occupied by
    //    Text Speed / Input Type, so the rows go on a separate backdrop panel to the RIGHT
    //    of the options window (teal, textured from options_panel.png when present).
    public static class Patch_Options
    {
        const string MARKER = "SRRVoicesOptionsRows";
        const string PANEL_PNG = "options_panel.png";

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

                bool sidePanel = screen.GetType().Name == "PDAAnchor";

                // one row's worth of vertical offset, measured from the game's own layout
                Vector3 dText = soundText.transform.localPosition - ambientText.transform.localPosition;
                Vector3 dSlider = soundSlider.transform.localPosition - ambientSlider.transform.localPosition;

                // side-panel mode: shift every clone right of the options window's audio backdrop
                Vector3 shift = Vector3.zero;
                Component bg = GetComp(screen, "audioBG");
                if (sidePanel)
                {
                    Bounds row = WidgetBounds(parent, soundText.transform);
                    Encapsulate(ref row, WidgetBounds(parent, soundSlider.transform));
                    float bgRight = row.max.x;
                    if (bg != null)
                    {
                        // NGUIMath handles the sprite's pivot; position+scale/2 assumed a centered
                        // pivot, which the PDA prefab's audioBG does not have (panel overlapped the window)
                        bgRight = WidgetBounds(parent, bg.transform).max.x;
                    }
                    float nx = (Plugin.CfgPdaNudgeX != null) ? Plugin.CfgPdaNudgeX.Value : 0f;
                    float ny = (Plugin.CfgPdaNudgeY != null) ? Plugin.CfgPdaNudgeY.Value : 0f;
                    // 120 clears the metal window frame that extends past audioBG; 30 = panel pad
                    shift = new Vector3(bgRight + 120f + 30f - row.min.x + nx, -dText.y + ny, 0f);
                }

                GameObject holder = new GameObject(MARKER);
                holder.transform.parent = parent;
                holder.transform.localPosition = Vector3.zero;
                holder.transform.localScale = Vector3.one;
                OptionsRowsHandler handler = holder.AddComponent<OptionsRowsHandler>();

                Component title = null;
                if (sidePanel) title = CloneLabel(soundText, shift, "AI Voices");

                handler.volLabel = CloneLabel(soundText, shift + dText, "Voice Volume");
                Component volSlider = CloneSlider(soundSlider, shift + dSlider, holder, "OnVoiceVolumeSliderChange");
                SetSliderValue(volSlider, (Plugin.CfgVolume != null) ? Mathf.Clamp01(Plugin.CfgVolume.Value) : 1f);

                handler.spdLabel = CloneLabel(soundText, shift + dText * 2f, "Voice Speed");
                Component spdSlider = CloneSlider(soundSlider, shift + dSlider * 2f, holder, "OnVoiceSpeedSliderChange");
                SetSliderValue(spdSlider, SpeedToSlider((Plugin.CfgSpeed != null) ? Plugin.CfgSpeed.Value : 1f));
                handler.UpdateSpeedLabel();

                // AI portraits: a clickable label rather than a slider — it's a yes/no setting,
                // and NGUI raises OnClick on whatever GameObject owns the collider. Only shown when
                // a portrait pack actually shipped, so a voices-only build has no dead toggle.
                Component portLabel = PortraitPatches.Available
                    ? CloneLabel(soundText, shift + dText * 3f, "AI Portraits") : null;
                if (portLabel != null)
                {
                    AddWidgetCollider(portLabel.gameObject);
                    PortraitToggleRow row3 = portLabel.gameObject.AddComponent<PortraitToggleRow>();
                    row3.label = portLabel;
                    row3.Refresh();
                }

                if (sidePanel)
                {
                    Bounds all = WidgetBounds(parent, handler.volLabel.transform);
                    if (title != null) Encapsulate(ref all, WidgetBounds(parent, title.transform));
                    Encapsulate(ref all, WidgetBounds(parent, handler.spdLabel.transform));
                    if (volSlider != null) Encapsulate(ref all, WidgetBounds(parent, volSlider.transform));
                    if (spdSlider != null) Encapsulate(ref all, WidgetBounds(parent, spdSlider.transform));
                    if (portLabel != null) Encapsulate(ref all, WidgetBounds(parent, portLabel.transform));
                    MakeBackdrop(parent, all, 30f, 26f, MinWidgetDepth(holder, title, handler, volSlider, spdSlider) - 1, bg);
                }
                else if (bg != null)
                {
                    // main menu: grow the audio panel background to make room for the extra rows
                    // (Volume + Speed, plus the AI-portraits toggle when a pack shipped)
                    Vector3 s = bg.transform.localScale;
                    float grow = Mathf.Abs(dText.y) * (portLabel != null ? 3f : 2f);
                    bg.transform.localScale = new Vector3(s.x, s.y + grow, s.z);
                    // extend toward wherever the new rows went (rows stack in the dText direction)
                    bg.transform.localPosition += new Vector3(0f, Mathf.Sign(dText.y) * grow / 2f, 0f);
                }
                if (Plugin.Log != null)
                    Plugin.Log.LogInfo("Options (" + screen.GetType().Name + "): voice rows injected" +
                                       (sidePanel ? " as side panel." : " inline.") +
                                       (portLabel != null ? " (with AI portraits toggle)" : ""));
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("options inject: " + e.Message);
            }
        }

        // ---- side-panel helpers -------------------------------------------------

        static Type FindType(string name)
        {
            Type t = typeof(ConversationManager).Assembly.GetType(name);
            if (t != null) return t;
            foreach (System.Reflection.Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                t = asm.GetType(name);
                if (t != null) return t;
            }
            return null;
        }

        static Bounds WidgetBounds(Transform root, Transform child)
        {
            Type t = FindType("NGUIMath");
            if (t != null)
            {
                var m = t.GetMethod("CalculateRelativeWidgetBounds",
                                    new Type[] { typeof(Transform), typeof(Transform) });
                if (m != null)
                    return (Bounds)m.Invoke(null, new object[] { root, child });
            }
            return new Bounds(root.InverseTransformPoint(child.position), new Vector3(200f, 24f, 0f));
        }

        static void Encapsulate(ref Bounds b, Bounds other)
        {
            b.Encapsulate(other.min);
            b.Encapsulate(other.max);
        }

        static int MinWidgetDepth(GameObject holder, Component title, OptionsRowsHandler handler, Component volSlider, Component spdSlider)
        {
            int min = 0;
            Type widgetType = FindType("UIWidget");
            if (widgetType == null) return min;
            Component[] roots = new Component[] { title, handler.volLabel, handler.spdLabel, volSlider, spdSlider };
            bool found = false;
            foreach (Component c in roots)
            {
                if (c == null) continue;
                foreach (Component w in c.GetComponentsInChildren(widgetType, true))
                {
                    var p = AccessTools.Property(widgetType, "depth");
                    if (p == null) continue;
                    int d = (int)p.GetValue(w, null);
                    if (!found || d < min) { min = d; found = true; }
                }
            }
            return min;
        }

        static Texture2D LoadPanelTexture()
        {
            try
            {
                string path = Path.Combine(Path.Combine(Paths.PluginPath, "SRRVoices"), PANEL_PNG);
                if (!File.Exists(path)) return null;
                byte[] bytes = File.ReadAllBytes(path);
                Texture2D tex = new Texture2D(2, 2, TextureFormat.ARGB32, false);
                if (!tex.LoadImage(bytes)) return null;
                return tex;
            }
            catch (Exception) { return null; }
        }

        static void MakeBackdrop(Transform parent, Bounds content, float padX, float padY, int depth, Component templateSprite)
        {
            Vector3 center = content.center;
            Vector3 size = new Vector3(content.size.x + padX * 2f, content.size.y + padY * 2f, 1f);

            Texture2D tex = LoadPanelTexture();
            Type texType = FindType("UITexture");
            if (tex != null && texType != null)
            {
                GameObject go = new GameObject("SRRVoices_PanelBG");
                go.layer = parent.gameObject.layer;
                go.transform.parent = parent;
                go.transform.localRotation = Quaternion.identity;
                go.transform.localPosition = center;
                go.transform.localScale = size;
                Component ut = go.AddComponent(texType);
                Material mat = new Material(Shader.Find("Unlit/Transparent Colored"));
                mat.mainTexture = tex;
                // NGUI 2.x builds one draw call per material and does NOT order draw calls by
                // widget depth across materials; queue 2999 (< NGUI's 3000) guarantees this
                // backdrop renders behind the font and atlas draw calls (labels were invisible).
                mat.renderQueue = 2999;
                SetProp(ut, "material", mat);
                SetProp(ut, "depth", depth);
                if (Plugin.Log != null) Plugin.Log.LogInfo("options side panel: textured backdrop (" + PANEL_PNG + ").");
                return;
            }
            // fallback: clone the game's own audio backdrop sprite and tint it teal
            if (templateSprite != null)
            {
                GameObject go = UnityEngine.Object.Instantiate(templateSprite.gameObject) as GameObject;
                go.name = "SRRVoices_PanelBG";
                go.transform.parent = parent;
                go.transform.localRotation = Quaternion.identity;
                go.transform.localScale = size;
                go.transform.localPosition = center;
                Component sprite = go.GetComponent("UISprite");
                SetProp(sprite, "color", new Color(0.30f, 0.85f, 0.80f, 0.95f));
                SetProp(sprite, "depth", depth);
                if (Plugin.Log != null) Plugin.Log.LogInfo("options side panel: teal-tinted sprite backdrop (no " + PANEL_PNG + ").");
            }
        }

        // NGUI's own helper sizes the collider to the widget; fall back to a manual box.
        static void AddWidgetCollider(GameObject go)
        {
            try
            {
                Type nt = FindType("NGUITools");
                var m = (nt == null) ? null : nt.GetMethod("AddWidgetCollider", new Type[] { typeof(GameObject) });
                if (m != null) { m.Invoke(null, new object[] { go }); return; }
            }
            catch (Exception) { }
            BoxCollider bc = go.GetComponent<BoxCollider>();
            if (bc == null) bc = go.AddComponent<BoxCollider>();
            bc.isTrigger = true;
            bc.size = new Vector3(260f, 30f, 1f);
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
    // Lives on the label itself so NGUI's click routing finds it.
    public class PortraitToggleRow : MonoBehaviour
    {
        public Component label;

        public void OnClick()
        {
            if (Plugin.CfgPortraits == null) return;
            Plugin.CfgPortraits.Value = !Plugin.CfgPortraits.Value;
            Refresh();
            // apply straight away, so the next line of dialogue already reflects the change
            if (Plugin.CfgPortraits.Value) PortraitPatches.FixupScene();
        }

        public void Refresh()
        {
            if (label == null) return;
            bool on = (Plugin.CfgPortraits != null) && Plugin.CfgPortraits.Value;
            var p = HarmonyLib.AccessTools.Property(label.GetType(), "text");
            if (p != null) p.SetValue(label, "AI Portraits  " + (on ? "On" : "Off"), null);
        }
    }

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
