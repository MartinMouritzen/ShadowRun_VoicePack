using System;
using System.Collections;
using System.Runtime.InteropServices;
using UnityEngine;

namespace SRRVoices
{
    // Borderless fullscreen for the Unity 4 (Windows) game window.
    //
    // Unity 4's fullscreen is an exclusive mode-set, so Windows minimizes the game every time it
    // loses focus. The fix is to run *windowed* at desktop resolution and then strip the window
    // chrome (WS_POPUP) and cover the monitor: it looks fullscreen but behaves like an ordinary
    // window, so alt-tab, a second monitor and overlays all keep working.
    //
    // Two things make this more than a one-shot SetWindowLong, which is why this runs as a watchdog
    // rather than once at startup:
    //  - Screen.SetResolution is deferred to the end of the frame, and Unity rebuilds the window
    //    (with its normal chrome) when it applies. The restyle has to happen on a later frame.
    //  - The game re-asserts its own resolution/fullscreen setting - the options screen, Unity's
    //    built-in alt+enter toggle - which puts the border back. The watchdog undoes that.
    //
    // Note on sharpness: a DPI-unaware process gets a virtualized desktop size (e.g. 2752x1152 on a
    // 3440x1440 screen at 125% scaling) and Windows then upscales the window, which looks soft.
    // Hong Kong's player calls SetProcessDPIAware itself; Dragonfall's and Dead Man's Switch's do
    // not, so they need the exe's "Override high DPI scaling behavior: Application" compat flag.
    // We can't fix that from here (it has to be set before the window exists), so we detect it and
    // say so in the log.
    public static class BorderlessWindow
    {
        const int GWL_STYLE = -16;
        const int GWL_EXSTYLE = -20;

        const int WS_POPUP = unchecked((int)0x80000000);
        const int WS_VISIBLE = 0x10000000;
        const int WS_BORDER = 0x00800000;
        const int WS_DLGFRAME = 0x00400000;
        const int WS_CAPTION = WS_BORDER | WS_DLGFRAME;
        const int WS_THICKFRAME = 0x00040000;
        const int WS_SYSMENU = 0x00080000;
        const int WS_MINIMIZEBOX = 0x00020000;
        const int WS_MAXIMIZEBOX = 0x00010000;
        const int WS_CHROME = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX;

        const int WS_EX_DLGMODALFRAME = 0x00000001;
        const int WS_EX_CLIENTEDGE = 0x00000200;
        const int WS_EX_STATICEDGE = 0x00020000;
        const int WS_EX_WINDOWEDGE = 0x00000100;

        const uint SWP_NOSIZE = 0x0001;
        const uint SWP_NOMOVE = 0x0002;
        const uint SWP_NOZORDER = 0x0004;
        const uint SWP_FRAMECHANGED = 0x0020;
        const uint SWP_SHOWWINDOW = 0x0040;

        const uint GW_OWNER = 4;
        const uint MONITOR_DEFAULTTOPRIMARY = 1;
        const int ENUM_CURRENT_SETTINGS = -1;

        [StructLayout(LayoutKind.Sequential)]
        struct RECT { public int left, top, right, bottom; }

        [StructLayout(LayoutKind.Sequential)]
        struct MONITORINFO { public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags; }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
        struct DEVMODE
        {
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
            public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra;
            public int dmFields;
            public int dmPositionX, dmPositionY;
            public int dmDisplayOrientation, dmDisplayFixedOutput;
            public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
            public short dmLogPixels;
            public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
            public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2;
            public int dmPanningWidth, dmPanningHeight;
        }

        delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")] static extern IntPtr GetActiveWindow();
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
        [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hWnd);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hWnd);
        [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr hWnd, uint cmd);
        [DllImport("user32.dll", SetLastError = true)] static extern int GetWindowLong(IntPtr hWnd, int nIndex);
        [DllImport("user32.dll", SetLastError = true)] static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);
        [DllImport("user32.dll", SetLastError = true)]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
        [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
        [DllImport("user32.dll")] static extern IntPtr MonitorFromWindow(IntPtr hWnd, uint flags);
        [DllImport("user32.dll")] static extern bool GetMonitorInfo(IntPtr hMonitor, ref MONITORINFO mi);
        [DllImport("user32.dll")] static extern int GetSystemMetrics(int index);
        [DllImport("user32.dll", CharSet = CharSet.Ansi)]
        static extern bool EnumDisplaySettings(string device, int mode, ref DEVMODE dm);
        [DllImport("kernel32.dll")] static extern uint GetCurrentProcessId();
        [DllImport("user32.dll", CharSet = CharSet.Ansi)]
        static extern int GetClassName(IntPtr h, System.Text.StringBuilder sb, int max);
        [DllImport("user32.dll", CharSet = CharSet.Ansi)]
        static extern int GetWindowText(IntPtr h, System.Text.StringBuilder sb, int max);

        static IntPtr _hwnd;
        static EnumWindowsProc _enumProc;   // kept alive across the P/Invoke

        static bool _applied;     // we own the window right now
        static bool _saved;       // original style/rect captured, so we can put it back
        static bool _settled;     // steady state reached (logged once per settle)
        static bool _gaveUp;      // the player won; stop before this turns into a flicker loop
        static bool _prevWant;    // last seen value of the setting, to notice a fresh opt-in
        static int _attempts;     // restyle attempts since the last settle
        static int _stable;       // consecutive ticks the window has not changed under us
        static int _lastStyle;
        static RECT _lastRect;
        static int _savedStyle, _savedExStyle;
        static RECT _savedRect;
        static float _lastResChange = -10f;
        static bool _loggedDpi;

        // Win32 only - the Mac and Linux players get nothing to toggle.
        public static bool Supported
        {
            get
            {
                return Application.platform == RuntimePlatform.WindowsPlayer ||
                       Application.platform == RuntimePlatform.WindowsEditor;
            }
        }

        // Called from the plugin once, whether or not the option is on: the watchdog picks the
        // setting up live, so toggling it in the in-game options applies without a restart.
        public static IEnumerator Watch()
        {
            if (!Supported) yield break;

            // Let Unity finish applying its own boot resolution before touching anything.
            yield return null;
            yield return null;

            float last = -10f;
            while (true)
            {
                if (Time.realtimeSinceStartup - last >= 0.3f)
                {
                    last = Time.realtimeSinceStartup;
                    bool want = Plugin.CfgBorderless != null && Plugin.CfgBorderless.Value;
                    if (want && !_prevWant) { _gaveUp = false; _attempts = 0; _stable = 0; }
                    _prevWant = want;
                    try
                    {
                        if (want) Tick();
                        else if (_applied) Restore();
                    }
                    catch (Exception e)
                    {
                        if (Plugin.Log != null) Plugin.Log.LogWarning("borderless: " + e.Message);
                        yield break;
                    }
                }
                // frame-based rather than WaitForSeconds: the game pauses with timeScale 0 while the
                // options screen is open, which is exactly when the toggle gets flipped.
                yield return null;
            }
        }

        // Every decision is made from Win32 state, never from Screen.width: Unity's Screen.width
        // lags an external restyle and reports the client size of the frame it *thinks* it has.
        //
        // The important rule here is "only touch a window that has stopped moving". Leaving
        // exclusive fullscreen takes Unity several frames, during which it re-creates and re-styles
        // the window; restyling in the middle of that just makes both sides fight, which on screen
        // is a window flickering between bordered and borderless. So we wait for the window to hold
        // still, then restyle once, then wait again. If Unity keeps winning we stop rather than
        // flicker forever.
        static void Tick()
        {
            if (_gaveUp) return;

            IntPtr hwnd = GameWindow();
            if (hwnd == IntPtr.Zero) return;

            RECT mon = MonitorRect(hwnd);
            int w = mon.right - mon.left, h = mon.bottom - mon.top;
            if (w <= 0 || h <= 0) return;

            // Step 1: out of exclusive fullscreen. Toggling the property (rather than asking for a
            // resolution) keeps Unity's own requested size, so there is nothing for it to enforce
            // afterwards - it adopts whatever size the window ends up at.
            if (Screen.fullScreen)
            {
                if (Time.realtimeSinceStartup - _lastResChange < 1.5f) return;
                _lastResChange = Time.realtimeSinceStartup;
                Trace("leaving exclusive fullscreen (" + Screen.width + "x" + Screen.height + ")");
                Screen.fullScreen = false;
                _stable = 0;
                _settled = false;
                return;
            }

            int style = GetWindowLong(hwnd, GWL_STYLE);
            RECT r;
            if (!GetWindowRect(hwnd, out r)) return;

            bool stripped = (style & WS_CHROME) == 0;
            bool placed = r.left == mon.left && r.top == mon.top &&
                          (r.right - r.left) == w && (r.bottom - r.top) == h;
            if (stripped && placed)
            {
                _applied = true;
                _attempts = 0;
                if (!_settled)
                {
                    _settled = true;
                    if (Plugin.Log != null)
                        Plugin.Log.LogInfo("borderless: settled, window " + w + "x" + h + " at " +
                                           mon.left + "," + mon.top + ", Unity renders " +
                                           Screen.width + "x" + Screen.height);
                }
                return;
            }
            _settled = false;

            // Hold off while the window is still being moved around by the player.
            if (style != _lastStyle || !Same(r, _lastRect))
            {
                _lastStyle = style;
                _lastRect = r;
                _stable = 0;
                return;
            }
            if (++_stable < 3) return;    // ~1s of quiet
            _stable = 0;

            if (_attempts >= 8)
            {
                _gaveUp = true;
                if (Plugin.Log != null)
                    Plugin.Log.LogWarning("borderless: the player keeps restoring its own window, giving up " +
                                          "(the game stays windowed). Add -popupwindow to the game's Steam " +
                                          "launch options to get a borderless window from the player itself.");
                return;
            }
            _attempts++;

            if (!_saved)
            {
                _saved = true;
                _savedStyle = style;
                _savedExStyle = GetWindowLong(hwnd, GWL_EXSTYLE);
                _savedRect = r;
                WarnIfScaled(w, h);
            }

            // Style first, then move/size: the client area Unity is told about in the resulting
            // WM_SIZE is then computed against the new (frameless) window, so its back buffer comes
            // out at the full monitor size instead of a border's worth short.
            if (!stripped)
            {
                SetWindowLong(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE);
                SetWindowLong(hwnd, GWL_EXSTYLE,
                              GetWindowLong(hwnd, GWL_EXSTYLE) &
                              ~(WS_EX_DLGMODALFRAME | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE | WS_EX_WINDOWEDGE));
            }
            SetWindowPos(hwnd, IntPtr.Zero, mon.left, mon.top, w, h,
                         SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW);
            Trace("attempt " + _attempts + ": style 0x" + style.ToString("X8") + " -> 0x" +
                  GetWindowLong(hwnd, GWL_STYLE).ToString("X8") + ", " + w + "x" + h +
                  " at " + mon.left + "," + mon.top + " (unity " + Screen.width + "x" + Screen.height + ")");
        }

        static bool Same(RECT a, RECT b)
        {
            return a.left == b.left && a.top == b.top && a.right == b.right && a.bottom == b.bottom;
        }

        // Put the window back the way we found it, so turning the option off in-game is not a
        // "restart the game" change.
        static void Restore()
        {
            _applied = false;
            _settled = false;
            IntPtr hwnd = GameWindow();
            if (hwnd == IntPtr.Zero || !_saved) return;
            _saved = false;
            SetWindowLong(hwnd, GWL_STYLE, _savedStyle);
            SetWindowLong(hwnd, GWL_EXSTYLE, _savedExStyle);
            int w = _savedRect.right - _savedRect.left, h = _savedRect.bottom - _savedRect.top;
            if (w > 0 && h > 0)
                SetWindowPos(hwnd, IntPtr.Zero, _savedRect.left, _savedRect.top, w, h,
                             SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW);
            if (Plugin.Log != null) Plugin.Log.LogInfo("borderless: window restored.");
        }

        // The player can own more than one top-level window, so prefer the Unity render window by
        // class name and only fall back to "first visible unowned window of this process".
        static IntPtr GameWindow()
        {
            if (_hwnd != IntPtr.Zero && IsWindow(_hwnd)) return _hwnd;

            uint mine = GetCurrentProcessId();
            IntPtr unity = IntPtr.Zero, any = IntPtr.Zero;
            _enumProc = delegate(IntPtr h, IntPtr l)
            {
                uint pid;
                GetWindowThreadProcessId(h, out pid);
                if (pid != mine || !IsWindowVisible(h)) return true;
                if (GetWindow(h, GW_OWNER) != IntPtr.Zero) return true;   // skip owned tool windows
                if (ClassOf(h) == "UnityWndClass") { unity = h; return false; }
                if (any == IntPtr.Zero) any = h;
                return true;
            };
            EnumWindows(_enumProc, IntPtr.Zero);

            IntPtr found = (unity != IntPtr.Zero) ? unity : any;
            if (found == IntPtr.Zero) found = GetActiveWindow();
            if (found != IntPtr.Zero && Plugin.Log != null)
                Plugin.Log.LogInfo("borderless: window 0x" + found.ToInt32().ToString("X") +
                                   " class=" + ClassOf(found) + " title=" + TitleOf(found));
            _hwnd = found;
            return found;
        }

        static string ClassOf(IntPtr h)
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder(256);
            GetClassName(h, sb, sb.Capacity);
            return sb.ToString();
        }

        static string TitleOf(IntPtr h)
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder(256);
            GetWindowText(h, sb, sb.Capacity);
            return sb.ToString();
        }

        static RECT MonitorRect(IntPtr hwnd)
        {
            IntPtr mon = MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY);
            MONITORINFO mi = new MONITORINFO();
            mi.cbSize = Marshal.SizeOf(typeof(MONITORINFO));
            if (mon != IntPtr.Zero && GetMonitorInfo(mon, ref mi)) return mi.rcMonitor;

            RECT r = new RECT();
            r.left = 0; r.top = 0;
            r.right = GetSystemMetrics(0);    // SM_CXSCREEN
            r.bottom = GetSystemMetrics(1);   // SM_CYSCREEN
            return r;
        }

        // Step-by-step trace, capped so a pathological fight cannot fill the log.
        static int _traced;
        static void Trace(string msg)
        {
            if (_traced >= 20 || Plugin.Log == null) return;
            _traced++;
            Plugin.Log.LogInfo("borderless: " + msg + (_traced == 20 ? " (further steps not logged)" : ""));
        }

        // A DPI-unaware process sees the scaled desktop size, so the borderless window renders at
        // e.g. 2752x1152 and Windows stretches it. Nothing we can do from inside the process - say
        // so once, with the fix.
        static void WarnIfScaled(int w, int h)
        {
            if (_loggedDpi) return;
            _loggedDpi = true;
            DEVMODE dm = new DEVMODE();
            dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
            if (!EnumDisplaySettings(null, ENUM_CURRENT_SETTINGS, ref dm)) return;
            if (dm.dmPelsWidth <= w && dm.dmPelsHeight <= h) return;
            if (Plugin.Log != null)
                Plugin.Log.LogWarning("borderless: Windows is scaling this process (" + w + "x" + h +
                                      " of a " + dm.dmPelsWidth + "x" + dm.dmPelsHeight + " desktop), so the " +
                                      "picture will be upscaled. Fix: exe Properties -> Compatibility -> " +
                                      "Change high DPI settings -> Override high DPI scaling behavior: Application.");
        }
    }
}
