#!/usr/bin/env bash
# Assemble an installable, ISOLATED distribution for ONE game under dist/<game>/ :
# BepInEx x86 + entrypoint config + the SRRVoices plugin + that game's voicepack.
# Each game ships as its own release / Nexus mod. Run tools/build_voicepack.py <game> first
# (this script calls it) and plugin/build.sh to (re)build the DLL.
# Usage: build_dist.sh [dms|dragonfall|hk]   (default dms)
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
GAME_ID="${1:-dms}"
case "$GAME_ID" in dms|dragonfall|hk) ;; *) echo "unknown game '$GAME_ID'"; exit 2 ;; esac

DIST="$ROOT/dist/$GAME_ID"
VP="$ROOT/voicepack/$GAME_ID"
PLUGIN_DLL="$ROOT/plugin/SRRVoices/bin/SRRVoices.dll"
[ -f "$PLUGIN_DLL" ] || { echo "ERROR: build the plugin first (plugin/build.sh)"; exit 1; }

# (re)build this game's voicepack so dist is always current
python3 tools/build_voicepack.py "$GAME_ID"

rm -rf "$DIST"; mkdir -p "$DIST"
# 1. BepInEx x86 loader (winhttp.dll, doorstop, BepInEx/core) — shared across games
cp -r "$ROOT/bepinex_dist/." "$DIST/"
# 1b. Vortex compatibility marker: a copy of the Doorstop proxy named dinput8.dll.
# The GAME loads winhttp.dll (verified in its PE import table), which is what actually boots BepInEx;
# dinput8.dll is NOT imported by the game, so it never loads and is completely inert in-game.
# Its ONLY purpose is to trigger Vortex's built-in, game-agnostic "dinput" installer, which deploys
# the whole archive to the GAME ROOT (copy-only: it never rewrites BepInEx.cfg and never renames the
# mod). This makes the green "Mod Manager Download" button work in stock Vortex for anyone already
# managing the game the normal way — no custom game extension and no PR required. Do not remove.
cp "$DIST/winhttp.dll" "$DIST/dinput8.dll"
# 2. Entrypoint config: per-game override (dist_template/<game>/BepInEx.cfg) if present, else shared
mkdir -p "$DIST/BepInEx/config"
if [ -f "$ROOT/dist_template/$GAME_ID/BepInEx.cfg" ]; then
  cp "$ROOT/dist_template/$GAME_ID/BepInEx.cfg" "$DIST/BepInEx/config/BepInEx.cfg"
else
  cp "$ROOT/dist_template/BepInEx.cfg" "$DIST/BepInEx/config/BepInEx.cfg"
fi
# 3. Plugin + this game's voicepack
mkdir -p "$DIST/BepInEx/plugins/SRRVoices/voicepack/clips"
cp "$PLUGIN_DLL" "$DIST/BepInEx/plugins/SRRVoices/SRRVoices.dll"
cp "$VP/voicepack.index" "$DIST/BepInEx/plugins/SRRVoices/voicepack/"
cp "$VP/voicepack.json"  "$DIST/BepInEx/plugins/SRRVoices/voicepack/" 2>/dev/null || true
cp "$VP/clips/"*.ogg "$DIST/BepInEx/plugins/SRRVoices/voicepack/clips/" 2>/dev/null || true

CLIPS=$(ls "$DIST/BepInEx/plugins/SRRVoices/voicepack/clips/" 2>/dev/null | wc -l)
NODES=$(grep -vc '^#' "$DIST/BepInEx/plugins/SRRVoices/voicepack/voicepack.index" 2>/dev/null || echo 0)
SIZE=$(du -sh "$DIST" | cut -f1)
echo "dist/$GAME_ID assembled: $NODES voiced nodes, $CLIPS clips, $SIZE total"
echo "  install by copying dist/$GAME_ID/* into the game root, or zip it for a Nexus release"
