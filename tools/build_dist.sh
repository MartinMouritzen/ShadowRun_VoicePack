#!/usr/bin/env bash
# Assemble the installable distribution under dist/ : BepInEx x86 + Camera-entrypoint config +
# the SRRVoices plugin + the current voicepack. Run tools/build_voicepack.py and plugin/build.sh first.
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
DIST="$ROOT/dist"

PLUGIN_DLL="$ROOT/plugin/SRRVoices/bin/SRRVoices.dll"
[ -f "$PLUGIN_DLL" ] || { echo "ERROR: build the plugin first (plugin/build.sh)"; exit 1; }
[ -f "$ROOT/voicepack/voicepack.index" ] || { echo "ERROR: build the voicepack first (tools/build_voicepack.py)"; exit 1; }

rm -rf "$DIST"; mkdir -p "$DIST"
# 1. BepInEx x86 loader (winhttp.dll, doorstop, BepInEx/core)
cp -r "$ROOT/bepinex_dist/." "$DIST/"
# 2. Camera-entrypoint config (pre-seeded)
mkdir -p "$DIST/BepInEx/config"
cp "$ROOT/dist_template/BepInEx.cfg" "$DIST/BepInEx/config/BepInEx.cfg"
# 3. Plugin + voicepack
mkdir -p "$DIST/BepInEx/plugins/SRRVoices/voicepack/clips"
cp "$PLUGIN_DLL" "$DIST/BepInEx/plugins/SRRVoices/SRRVoices.dll"
cp "$ROOT/voicepack/voicepack.index" "$DIST/BepInEx/plugins/SRRVoices/voicepack/"
cp "$ROOT/voicepack/voicepack.json"  "$DIST/BepInEx/plugins/SRRVoices/voicepack/" 2>/dev/null || true
cp "$ROOT/voicepack/clips/"*.ogg "$DIST/BepInEx/plugins/SRRVoices/voicepack/clips/" 2>/dev/null || true

CLIPS=$(ls "$DIST/BepInEx/plugins/SRRVoices/voicepack/clips/" 2>/dev/null | wc -l)
SIZE=$(du -sh "$DIST" | cut -f1)
echo "dist/ assembled: $CLIPS clips, $SIZE total"
echo "  install by copying dist/* into the game root, or run tools/install.ps1"
find "$DIST" -maxdepth 3 -type d | sed "s#$DIST#dist#" | sort
