#!/usr/bin/env bash
# Export the current lab takes into the voicepack and install ONLY the changed files into the game
# (incremental — does not recopy the whole 180MB+ pack each time). Restart the game to load changes.
set -e
cd "$(dirname "$0")/.."
GAME="/mnt/c/Program Files (x86)/Steam/steamapps/common/Shadowrun Returns"
PLUG="$GAME/BepInEx/plugins/SRRVoices"

python3 tools/build_voicepack.py

if [ ! -d "$GAME" ]; then
  echo "GAME DIR NOT FOUND at $GAME — built voicepack but did not install."
  exit 1
fi

mkdir -p "$PLUG/voicepack/clips"
# manifest (always) + plugin dll (if newer)
cp -f voicepack/voicepack.index "$PLUG/voicepack/voicepack.index"
cp -f voicepack/voicepack.json  "$PLUG/voicepack/voicepack.json" 2>/dev/null || true
# cp -f (NOT -u): cp -u compares mtimes, which is unreliable across the WSL->NTFS boundary and
# would silently skip installing a newer DLL. The DLL is tiny, so always overwrite.
[ -f plugin/SRRVoices/bin/SRRVoices.dll ] && cp -f plugin/SRRVoices/bin/SRRVoices.dll "$PLUG/SRRVoices.dll" || true
# clips: copy only ones not already present (hash-named, immutable)
cp -rn voicepack/clips/. "$PLUG/voicepack/clips/" 2>/dev/null || true
# prune clips no longer referenced by the manifest (keeps the install from growing unbounded)
python3 - "$PLUG/voicepack" <<'PY'
import sys, os, json
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
echo "SYNCED: $N voiced nodes installed. RESTART the game to load them."
