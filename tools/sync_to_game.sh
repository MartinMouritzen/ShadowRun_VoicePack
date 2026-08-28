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

# Is the game running RIGHT NOW? A clip is named sha1(SOURCE TAKE PATH) (build_voicepack.py), and
# take filenames carry a timestamp, so selecting or regenerating a take yields a new source path ->
# a new clip name, and the old file becomes prunable. The running game read its manifest at startup
# and still points at those old names, so pruning under it silently kills every line we just changed
# ("load failed clips/<hash>.ogg") and turns any re-keyed portrait into grey noise. Copying new
# files in is harmless; only deletion is. So: never prune under a live game.
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
  # prune portraits the index no longer references (same reason the clip install reconciles both
  # ways: a re-picked portrait, or a character that turned out not to exist, otherwise leaves its
  # PNG behind in the install forever)
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
# cp -f (NOT -u): cp -u compares mtimes, which is unreliable across the WSL->NTFS boundary and
# would silently skip installing a newer DLL. The DLL is tiny, so always overwrite.
#
# It is also the one file a running game can refuse: Windows keeps a loaded assembly mapped, so the
# overwrite fails with a sharing violation. That used to be `|| true`, which swallowed it silently —
# you would see "SYNCED", restart, and still be on the old plugin with no clue why the fix you just
# built had no effect. Say so instead.
if [ -f plugin/SRRVoices/bin/SRRVoices.dll ]; then
  if ! cp -f plugin/SRRVoices/bin/SRRVoices.dll "$PLUG/SRRVoices.dll" 2>/dev/null; then
    echo "WARNING: could not replace SRRVoices.dll — the game holds the loaded copy open."
    echo "         Quit $GAME_ID and re-run this script, or the plugin stays at its old build."
  fi
fi
# clips FIRST, then the manifest that names them: the plugin reloads the manifest when its mtime
# changes (VoicePack.IndexChanged), so a live game can read it the instant it lands. Writing the
# index before its clips arrive gives it a window where every new line resolves to a file that is
# still being copied.
#
# This was `cp -rn`, which is correct but stats every destination file to decide whether to skip
# it. Across the WSL->NTFS boundary that costs ~1.5s per 500 files, so a no-op sync of 9,287 clips
# spent 3.7 of its 4.4 seconds deciding to do nothing. One readdir of the same directory costs
# 0.02s, so the difference is worked out in Python and only genuinely missing files are copied.
# The prune shares this listing instead of taking its own.
#
# "Missing by name" is the whole test ONLY while the encoder settings are fixed. Clip files are
# named sha1(SOURCE TAKE PATH), which says nothing about how the audio was encoded, so re-encoding
# yields the same filename holding different bytes and every installed clip is skipped. That is not
# hypothetical: the -14-loudnorm -> -18-flat-gain change reported "SYNCED" in 1s having copied
# nothing at all, leaving three games playing audio the pack no longer contained. So the packer now
# writes voicepack.stamp with its encoder settings, and a stamp mismatch forces a full re-copy.
python3 - "$VP/clips" "$PLUG/voicepack/clips" "$GAME_RUNNING" "$VP/voicepack.stamp" "$PLUG/voicepack/voicepack.stamp" <<'CLIPS'
import os, shutil, sys
src, dst, running = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
stamp_src, stamp_dst = sys.argv[4], sys.argv[5]
os.makedirs(dst, exist_ok=True)

def read_stamp(p):
    try:
        with open(p) as fh: return fh.read().strip()
    except OSError:
        return None

built = read_stamp(stamp_src)
reencoded = built is not None and built != read_stamp(stamp_dst)

have = set(os.listdir(dst))
want = set(os.listdir(src)) if os.path.isdir(src) else set()
todo = want if reencoded else (want - have)
added = 0
for f in sorted(todo):
    shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    added += 1
removed = 0
if not running:
    for f in have - want:
        try:
            os.remove(os.path.join(dst, f))
            removed += 1
        except OSError:
            pass
bits = []
if reencoded: bits.append("encoder settings changed -> full re-copy of %d" % added)
elif added:   bits.append("+%d new" % added)
if removed:   bits.append("-%d stale" % removed)
print("  clips: " + (", ".join(bits) if bits else "unchanged"))
if built is not None:
    with open(stamp_dst, "w", newline="\n") as fh: fh.write(built + "\n")
CLIPS
cp -f "$VP/voicepack.json"  "$PLUG/voicepack/voicepack.json" 2>/dev/null || true
# Gates before the index, same reasoning as clips-before-index: the plugin re-reads everything when
# voicepack.index changes mtime, so the gates it will consult must already be on disk by then.
cp -f "$VP/voicepack.gates" "$PLUG/voicepack/voicepack.gates" 2>/dev/null || true
cp -f "$VP/voicepack.index" "$PLUG/voicepack/voicepack.index"
N=$(grep -vc '^#' "$PLUG/voicepack/voicepack.index" 2>/dev/null || echo 0)
echo "SYNCED: $N voiced nodes installed to $GAME_ID. A running game picks this up within ~2s."
if [ "$GAME_RUNNING" = 1 ]; then
  echo "NOTE: $GAME_ID is running, so stale files were left in place rather than pruned — a clip"
  echo "      deleted in the seconds before the game notices the new manifest is a line that fails"
  echo "      to load. Re-run this after quitting to clear the leftovers."
fi
