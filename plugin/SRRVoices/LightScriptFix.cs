using System;
using HarmonyLib;

namespace SRRVoices
{
    // A VANILLA BUG, not one of ours, and it makes a save permanently unloadable.
    //
    // Animated props carry a light script and the game time the animation started, saved per prop as
    // "LightScript" / "LightStart". On restore, PropLightComponent fast-forwards the animation to the
    // right phase by handing the whole elapsed time to UpdateLightTransition in one go:
    //
    //     lightScriptDuration = startAtDuration;                  // LightStart, e.g. 29,415,360
    //     if (lightScriptDuration > 0f) UpdateLightTransition(lightScriptDuration);
    //
    // and that walks the intervals one at a time:
    //
    //     intervalTime += deltaTime;                              // 29,415,360
    //     while (intervalTime > intervalDuration)
    //     {
    //         intervalTime -= intervalDuration;                   // 1.0 for a "hard:01" step
    //         currentInterval = nextInterval;
    //         RefreshInterval();
    //         if (nextInterval < 0) return;                       // never fires for a "loop" script
    //     }
    //
    // intervalTime is a float32, and at 29.4 million its ULP is 2.0 — so `intervalTime -= 1.0` does
    // not change the value at all. The condition can never go false, RefreshInterval just cycles
    // round a looped script forever, and the main thread spins inside a scene load that therefore
    // never completes. Not slow: stuck. Waiting does not help.
    //
    // Diagnosed 2026-08-13 on a Dragonfall quicksave inside Das Kesselhaus (the nightclub, so: a lot
    // of flashing lights). It hung on prop 5,827 of 5,908, deterministically, at the same prop with
    // the plugin fully removed. That save had ten lights with a huge LightStart: four "cubic:05"
    // ones survived, because subtracting 5.0 does still move a float at ULP 2.0 — they merely burned
    // ~5.9 million iterations each, which is where the load's stalling slowness came from — and the
    // "hard:01" pair could not move at all.
    //
    // The fix: a looping animation's phase is periodic, so fast-forwarding 340 days of it is
    // pointless work with an exact cheap equivalent. Reduce the jump modulo the script's own loop
    // length before the walk starts. Same visual phase, no precision cliff, no millions of
    // iterations. Ordinary per-frame calls (deltaTime ~0.016) are never touched.
    public static class Patch_LightScriptPhase
    {
        static bool logged;

        // Well below the precision cliff (which for a 1.0s step starts around 1.7M) but far above any
        // real frame delta, and already high enough that the walk would be pointless busy-work.
        const float BIG_JUMP = 1000f;

        public static void Prefix(object __instance, ref float deltaTime)
        {
            try
            {
                if (deltaTime < BIG_JUMP || __instance == null) return;

                // Sum the interval durations = one trip round the loop. Reflected because
                // LightInterval is an engine type whose shape we should not bake into this build.
                var f = AccessTools.Field(__instance.GetType(), "intervalList");
                var list = (f == null) ? null : f.GetValue(__instance) as System.Collections.IList;
                float total = 0f;
                if (list != null)
                {
                    for (int i = 0; i < list.Count; i++)
                    {
                        object iv = list[i];
                        if (iv == null) continue;
                        var df = AccessTools.Field(iv.GetType(), "duration");
                        if (df == null) continue;
                        object dv = df.GetValue(iv);
                        if (dv is float) total += (float)dv;
                    }
                }

                float before = deltaTime;
                // No usable loop length (a non-looping or malformed script): start it from the top
                // rather than risk the same walk. Zero is a legal phase for any script.
                deltaTime = (total > 0.05f) ? (before % total) : 0f;

                if (!logged && Plugin.Log != null)
                {
                    logged = true;
                    Plugin.Log.LogWarning("light-script phase clamped: " + before + "s -> " + deltaTime
                        + "s (loop length " + total + "s). This is the vanilla infinite-loop hang on "
                        + "loading a save with animated lights; see Patch_LightScriptPhase.");
                }
            }
            catch (Exception e)
            {
                if (Plugin.Log != null) Plugin.Log.LogWarning("light-script clamp: " + e.Message);
            }
        }
    }
}
