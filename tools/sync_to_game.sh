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

# Is the game running RIGHT NOW? Clip and portrait files are named by content hash, so anything
# whose take changed gets a new name and the old file becomes prunable. The running game read its
# manifest at startup and still points at those old names, so pruning under it silently kills every
# line we just changed ("load failed clips/<hash>.ogg") and turns any re-keyed portrait into grey
# noise. Copying new files in is harmless; only deletion is. So: never prune under a live game.
GAME_RUNNING=0
if command -v powershell.exe >/dev/null 2>&1; then
  if powershell.exe -NoProfile -Command "if (Get-Process -Name Shadowrun,Dragonfall,SRHK -ErrorAction SilentlyContinue) { 'yes' }" 2>/dev/null | tr -d '\r' | grep -q yes; then
    GAME_RUNNING=1
  fi
fi

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
  # prune portraits the index no longer references (same reason as the clip prune below: a
  # re-picked portrait, or a character that turned out not to exist, otherwise leaves its PNG
  # behind in the install forever)
  [ "$GAME_RUNNING" = 1 ] || python3 - "$PLUG/portraits" <<'PY'
import sys, os
d = sys.argv[1]
keep = set()
for line in open(os.path.join(d, "portraits.index")):
    if line.startswith('#') or '\t' not in line: continue
    keep.add(os.path.basename(line.rstrip('\n').split('\t')[1]))
removed = 0
for f in os.listdir(d):
    if f.endswith(".png") and f not in keep:
        os.remove(os.path.join(d, f)); removed += 1
print(f"  pruned {removed} stale portrait(s)" if removed else "", end="")
PY
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
[ "$GAME_RUNNING" = 1 ] || python3 - "$PLUG/voicepack" <<'PY'
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
if [ "$GAME_RUNNING" = 1 ]; then
  echo "NOTE: $GAME_ID is running, so stale files were left in place rather than pruned — deleting"
  echo "      them under a live game silences the lines it already has open. The running session is"
  echo "      still on the OLD manifest either way: RESTART IT to hear anything that changed."
  echo "      Re-run this after quitting to clear the leftovers."
fi
