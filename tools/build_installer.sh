#!/usr/bin/env bash
# Compile a double-click Inno Setup installer for one game's AI Voice Pack.
# Requires the game's dist tree (tools/build_dist.sh <game>) and Inno Setup's ISCC.exe on Windows.
# Usage: build_installer.sh [dms|dragonfall|hk]   (default dms)
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
GAME_ID="${1:-dms}"

case "$GAME_ID" in
  dms)        NAME="Shadowrun Returns";                 EXE="Shadowrun.exe";  APPID="234650" ;;
  dragonfall) NAME="Shadowrun: Dragonfall Director's Cut"; EXE="Dragonfall.exe"; APPID="300550" ;;
  hk)         NAME="Shadowrun: Hong Kong";              EXE="SRHK.exe";       APPID="346940" ;;
  *) echo "unknown game '$GAME_ID' (expected dms|dragonfall|hk)"; exit 2 ;;
esac

DIST="$ROOT/dist/$GAME_ID"
[ -d "$DIST" ] || { echo "dist/$GAME_ID not found — run: bash tools/build_dist.sh $GAME_ID"; exit 1; }
VERSION="${VERSION:-1.1}"

# Locate ISCC.exe (Inno Setup 6). Override with ISCC env var if installed elsewhere.
# winget commonly installs to %LOCALAPPDATA%\Programs\Inno Setup 6.
ISCC_WIN="${ISCC:-C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe}"
# Windows path -> WSL path: backslashes to slashes, C:/c: to /mnt/c
win2wsl(){ printf '%s' "$1" | sed 's#\\#/#g; s#^[Cc]:#/mnt/c#'; }
ISCC_WSL="$(win2wsl "$ISCC_WIN")"
if [ ! -f "$ISCC_WSL" ]; then
  for cand in \
    "/mnt/c/Users/$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r')/AppData/Local/Programs/Inno Setup 6/ISCC.exe" \
    "/mnt/c/Program Files/Inno Setup 6/ISCC.exe" \
    "/mnt/c/Program Files (x86)/Inno Setup 6/ISCC.exe"; do
    [ -f "$cand" ] && { ISCC_WSL="$cand"; break; }
  done
fi
if [ ! -f "$ISCC_WSL" ]; then
  echo "Inno Setup ISCC.exe not found at: $ISCC_WIN"
  echo "Install Inno Setup 6 (https://jrsoftware.org/isdl.php) on Windows, or set ISCC=... , then re-run."
  echo "The script installer/srr-voices.iss is ready; you can also open it in the Inno Setup IDE and hit Compile."
  exit 3
fi

# Convert paths to Windows form for ISCC
winpath(){ printf '%s' "$1" | sed 's#/mnt/c#C:#; s#/#\\#g'; }
ISS_WIN="$(winpath "$ROOT/installer/srr-voices.iss")"
DIST_WIN="$(winpath "$DIST")"
OUT_WIN="$(winpath "$ROOT/dist")"

echo "Compiling installer for $GAME_ID ($NAME)…"
"$ISCC_WSL" \
  "/DGameId=$GAME_ID" "/DGameName=$NAME" "/DGameExe=$EXE" "/DSteamAppId=$APPID" \
  "/DAppVersion=$VERSION" "/DDistDir=$DIST_WIN" "/DOutDir=$OUT_WIN" \
  "$ISS_WIN" 2>&1 | tr -d '\r' | tail -20

echo "If it succeeded, the installer is at: dist/ShadowRun_VoicePack_${GAME_ID}_v${VERSION}_Setup.exe"
