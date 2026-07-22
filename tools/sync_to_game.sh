#!/usr/bin/env bash
# Export the current lab takes into the per-game voicepack and install ONLY the changed files into
# that game (incremental — does not recopy the whole pack each time). Restart the game to load.
# Usage: sync_to_game.sh [dms|dragonfall|hk]   (default dms)
set -e
cd "$(dirname "$0")/.."
GAME_ID="${1:-dms}"

STEAM="/mnt/c/Program Files (x86)/Steam/steamapps/common"
case "$GAME_ID" in
  dms)        GAME="$STEAM/Shadowrun Returns" ;;
  dragonfall) GAME="$STEAM/Shadowrun Dragonfall Director's Cut" ;;
  hk)         GAME="$STEAM/Shadowrun Hong Kong" ;;
  *) echo "unknown game '$GAME_ID' (expected dms|dragonfall|hk)"; exit 2 ;;
esac
PLUG="$GAME/BepInEx/plugins/SRRVoices"
VP="voicepack/$GAME_ID"

python3 tools/build_voicepack.py "$GAME_ID"
python3 tools/build_portraits.py "$GAME_ID" || true

if [ ! -d "$GAME" ]; then
  echo "GAME DIR NOT FOUND at $GAME — built voicepack but did not install."
  exit 1
fi

# AI portraits (optional; the plugin falls back to the game's own art when absent)
if [ -f "portraits_pack/$GAME_ID/portraits.index" ]; then
  mkdir -p "$PLUG/portraits"
  cp -f "portraits_pack/$GAME_ID/portraits.index" "$PLUG/portraits/portraits.index"
  cp -f portraits_pack/$GAME_ID/*.png "$PLUG/portraits/" 2>/dev/null || true
fi

mkdir -p "$PLUG/voicepack/clips"
# manifest (always) + plugin dll (if present). The DLL is shared across all three games.
cp -f "$VP/voicepack.index" "$PLUG/voicepack/voicepack.index"
cp -f "$VP/voicepack.json"  "$PLUG/voicepack/voicepack.json" 2>/dev/null || true
# cp -f (NOT -u): cp -u compares mtimes, which is unreliable across the WSL->NTFS boundary and
# would silently skip installing a newer DLL. The DLL is tiny, so always overwrite.
[ -f plugin/SRRVoices/bin/SRRVoices.dll ] && cp -f plugin/SRRVoices/bin/SRRVoices.dll "$PLUG/SRRVoices.dll" || true
# clips: copy only ones not already present (hash-named, immutable)
cp -rn "$VP/clips/." "$PLUG/voicepack/clips/" 2>/dev/null || true
# prune clips no longer referenced by the manifest (keeps the install from growing unbounded)
python3 - "$PLUG/voicepack" <<'PY'
import sys, os
vp=sys.argv[1]
idx=os.path.join(vp,"voicepack.index")
keep=set()
for line in open(idx):
    if line.startswith('#') or '\t' not in line: continue
    for c in line.rstrip('\n').split('\t')[1:]:
        keep.add(os.path.basename(c))
cd=os.path.join(vp,"clips")
removed=0
for f in os.listdir(cd):
    if f not in keep:
        os.remove(os.path.join(cd,f)); removed+=1
print(f"  pruned {removed} stale clips" if removed else "", end="")
PY

N=$(grep -vc '^#' "$PLUG/voicepack/voicepack.index" 2>/dev/null || echo 0)
echo "SYNCED: $N voiced nodes installed to $GAME_ID. RESTART the game to load them."
