#!/usr/bin/env bash
# Build SRRVoices.dll (net35 / x86) using the Windows .NET 3.5 csc.exe.
# Stages sources + reference DLLs under C:\temp\srrbuild (Windows-native path) to avoid
# \\wsl$ path issues, compiles, and copies the DLL back to plugin/SRRVoices/bin/.
set -e
cd "$(dirname "$0")"
PLUGDIR="$(pwd)"
STAGE_WIN='C:\temp\srrbuild'
STAGE='/mnt/c/temp/srrbuild'
CSC='/mnt/c/Windows/Microsoft.NET/Framework/v3.5/csc.exe'

rm -rf "$STAGE"; mkdir -p "$STAGE/lib"
cp SRRVoices/*.cs "$STAGE/"
cp lib/*.dll "$STAGE/lib/"

# Compose the csc command with Windows paths.
SRCS="Plugin.cs VoicePack.cs VoicePlayer.cs ConversationPatches.cs BorderlessWindow.cs InspectPatch.cs"
REFS='/reference:lib\BepInEx.dll /reference:lib\0Harmony.dll /reference:lib\UnityEngine.dll /reference:lib\Assembly-CSharp.dll /reference:lib\ShadowrunDTO.dll /reference:lib\protobuf-net.dll /reference:System.dll /reference:System.Core.dll'

cat > "$STAGE/compile.bat" <<BAT
@echo off
cd /d $STAGE_WIN
"$( echo $CSC | sed 's#/mnt/c#C:#; s#/#\\#g' )" /nologo /target:library /platform:x86 /warn:2 /out:SRRVoices.dll $REFS $SRCS
BAT

echo "Compiling..."
cmd.exe /c "$STAGE_WIN\\compile.bat" 2>&1 | tr -d '\r'
RC=${PIPESTATUS[0]}

if [ -f "$STAGE/SRRVoices.dll" ]; then
  mkdir -p "$PLUGDIR/SRRVoices/bin"
  cp "$STAGE/SRRVoices.dll" "$PLUGDIR/SRRVoices/bin/SRRVoices.dll"
  echo "OK -> plugin/SRRVoices/bin/SRRVoices.dll ($(stat -c%s "$PLUGDIR/SRRVoices/bin/SRRVoices.dll") bytes)"
else
  echo "BUILD FAILED (rc=$RC)"; exit 1
fi
