# Borderless fullscreen

Unity 4's fullscreen is an exclusive mode-set, so Windows minimizes the game every time it loses
focus: alt-tab, a click on a second monitor, a notification stealing focus. The cure is to run the
game **windowed at desktop resolution with the window chrome stripped** (`WS_POPUP`) so it looks
fullscreen but behaves like an ordinary window.

## Dead Man's Switch and Dragonfall: nothing to do

The voicepack plugin does it, and it is **on by default**. It waits for the player to settle, takes
the game out of exclusive fullscreen, strips the title bar and covers the monitor the window is on.

- Toggle it in-game: Escape menu / Options, the `BORDERLESS  ON/OFF` row under the voice settings.
  Turning it off puts the window back the way it was, no restart needed.
- Or edit `BepInEx/config/com.mmo.srrvoices.cfg`, `[Display] BorderlessFullscreen`.
- The BepInEx log records what happened (`borderless: settled, window 3440x1440 at 0,0 ...`).

## Hong Kong: two Steam settings

Hong Kong has no voicepack plugin yet, so use the Unity player's own borderless support:

1. Steam, right-click **Shadowrun: Hong Kong** -> Properties -> Launch Options: `-popupwindow`
2. In the game: Options -> Graphics -> **Fullscreen OFF**, resolution = your desktop resolution.

Both are required. `-popupwindow` only changes how the *windowed* window is built, so with the
in-game Fullscreen box still ticked you get an exclusive-fullscreen window that keeps minimizing.

(The same two settings work for Dead Man's Switch and Dragonfall if you would rather not use the
plugin's toggle. If the plugin ever loses the fight with the player it says so in the log and stops,
leaving the game windowed, and this is the fallback it points you at.)

## If the picture looks soft

A DPI-unaware process is handed the *scaled* desktop size (2752x1152 on a 3440x1440 screen at 125%
scaling) and Windows then stretches the result. Hong Kong's player calls `SetProcessDPIAware`
itself; the older Dead Man's Switch and Dragonfall players do not, so set it on the exe:

Properties -> Compatibility -> Change high DPI settings -> **Override high DPI scaling behavior:
Application**.

The plugin cannot do this from inside the process (it has to be set before the window exists), so it
detects the mismatch and writes a warning to the log instead.

## Why the plugin is a watchdog and not a one-shot

Two things bite anyone implementing this:

- `Screen.SetResolution` is deferred to the end of the frame, and applying it rebuilds the window
  with its normal chrome. Restyling immediately after the call gets silently undone.
- While Unity is switching out of exclusive fullscreen it re-creates and re-styles the window over
  several frames. Restyling in the middle of that makes both sides fight: the title bar flickers on
  and off and the window jumps around, which is exactly what a naive implementation looks like.

So the plugin only touches a window that has held still for ~1s, re-applies if the player takes it
back (the options screen and Unity's built-in alt+enter both do), and after 8 losing attempts gives
up and tells you to use `-popupwindow` rather than flicker forever.
