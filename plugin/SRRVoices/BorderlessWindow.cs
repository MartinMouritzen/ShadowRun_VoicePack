using System;
using System.Runtime.InteropServices;
using UnityEngine;

namespace SRRVoices
{
    // Borderless fullscreen for the Unity 4 (Windows) game window: set the game to a windowed
    // resolution matching the desktop, then strip the window chrome and reposition to 0,0.
    // (The zero-code alternative is the Steam launch option -popupwindow.)
    public static class BorderlessWindow
    {
        const int GWL_STYLE = -16;
        const uint WS_POPUP = 0x80000000;
        const uint WS_VISIBLE = 0x10000000;
        const uint SWP_NOZORDER = 0x0004;
        const uint SWP_FRAMECHANGED = 0x0020;
        const uint SWP_SHOWWINDOW = 0x0040;

        [DllImport("user32.dll")] static extern IntPtr GetActiveWindow();
        [DllImport("user32.dll", SetLastError = true)] static extern int GetWindowLong(IntPtr hWnd, int nIndex);
        [DllImport("user32.dll", SetLastError = true)] static extern int SetWindowLong(IntPtr hWnd, int nIndex, uint dwNewLong);
        [DllImport("user32.dll", SetLastError = true)]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
        [DllImport("user32.dll")] static extern int GetSystemMetrics(int nIndex);

        public static void Apply()
        {
            int w = GetSystemMetrics(0);   // SM_CXSCREEN
            int h = GetSystemMetrics(1);   // SM_CYSCREEN
            if (w <= 0 || h <= 0)
            {
                Resolution r = Screen.currentResolution;
                w = r.width; h = r.height;
            }
            // Windowed at desktop size first, then strip chrome.
            Screen.SetResolution(w, h, false);
            IntPtr hwnd = GetActiveWindow();
            if (hwnd == IntPtr.Zero) return;
            SetWindowLong(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE);
            SetWindowPos(hwnd, IntPtr.Zero, 0, 0, w, h,
                         SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW);
        }
    }
}
