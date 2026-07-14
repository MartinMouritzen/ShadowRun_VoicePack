# SRR AI Voices — BepInEx Plugin

Plays the lab's generated AI voice clips as each dialogue line appears in **Shadowrun Returns
(Dead Man Switch)**. Narrator and character segments play in order.

## Status (2026-07-13)

**Built and load-verified.** Everything testable without a human at the running game is done and
passing. The only step left is **you hearing it in-game** (audible playback needs a person + speakers).

### Verified
- Plugin compiles clean: `SRRVoices.dll` (net35 / x86) against the real game + BepInEx DLLs.
- **Full load chain confirmed via BepInEx log** (launched the game headless, read the log, killed it):
  - BepInEx 5.4.23.2 loads under Unity 4.2.0 with the **Camera entrypoint** (the #1 historic failure — works).
  - Plugin loads; **voicepack TSV parsed in the real Mono runtime** (23 nodes).
  - **Harmony patched all three methods** (ShowNodeText / StartConversation / EndConversation) with
    no errors — proving the method signatures match the shipped game.
- Voicepack export: ordered narrator→character clips, valid mono OGG Vorbis, TSV round-trips 1:1.

### NOT yet verified (needs you)
- **Audible playback** — that the OGG actually decodes and plays through the game's audio during a
  conversation, in sync with the dialogue box. The API path is the documented Unity-4 one and the
  community `SRAssetPatcherPlugin` confirms OGG-from-disk works in this exact game, so risk is low —
  but it must be confirmed by ear. If OGG somehow fails, the fallback is WAV (see plan doc risk #1).

## Build

```
plugin/build.sh          # compiles SRRVoices.dll via Windows csc.exe (net35/x86) into SRRVoices/bin/
```
Reference DLLs live in `plugin/lib/` (copied from the game's Managed dir + BepInEx core; not shipped).
Or open `SRRVoices/SRRVoices.csproj` in Visual Studio 2022.

## Full build + package pipeline

```
python3 tools/build_voicepack.py   # lab takes -> voicepack/ (MP3->OGG, ordered manifest + TSV index)
plugin/build.sh                    # -> plugin/SRRVoices/bin/SRRVoices.dll
tools/build_dist.sh                # assemble dist/  (BepInEx + config + plugin + voicepack)
# then install:
powershell -ExecutionPolicy Bypass -File tools/install.ps1     # auto-detects Steam game dir
```

## How to test in-game (your part)

1. The mod is **already installed** into your Shadowrun Returns folder. (Re-run `install.ps1` after
   generating more voices + re-running `build_voicepack.py` + `build_dist.sh` to refresh the pack.)
2. Launch **Shadowrun Returns from Steam** (normally — not headless).
3. The first voiced line you can reach is **Dresden in the morgue** (chapter 2, the first real
   conversation after the prologue). Talk to Dresden — you should hear his lines.
4. Other currently-voiced spots: Baron Samedi intro, Mrs. Kubota (Seamstresses), Coyote, the
   Mercy mental-hospital narration. (Only 23 nodes are voiced so far — whatever you generated in the
   lab. Generate the c01–c03 conversations, per `tools/opening_order.py`, for a full opening.)
5. Verify by ear: the clip plays when the line appears; multi-part lines play narrator-then-character;
   clicking Continue cuts the old clip and starts the next; leaving the conversation stops audio.
6. Check `<game>/BepInEx/LogOutput.log` — with `LogLines=true` (default) it prints `play <key>` /
   `no VO <key>` per node, so you can see exactly what it matched.

## Config

`<game>/BepInEx/config/com.mmo.srrvoices.cfg` (created on first run):
- `Enabled` (bool) — master on/off.
- `Volume` (0..1, default 0.9).
- `BorderlessFullscreen` (bool, default false) — force borderless at desktop res on startup.
  (Zero-code alternative: Steam launch option `-popupwindow` + in-game resolution = desktop.)
- `LogLines` (bool, default true) — log each played/missed node key.

## Uninstall

Delete from the game root: `winhttp.dll`, `doorstop_config.ini`, `.doorstop_version`, and the
entire `BepInEx\` folder.

## Files

- `SRRVoices/Plugin.cs` — entrypoint: config, load voicepack, persistent player, Harmony, fullscreen.
- `SRRVoices/ConversationPatches.cs` — Harmony patches on ShowNodeText / StartConversation / EndConversation.
- `SRRVoices/VoicePlayer.cs` — WWW OGG streaming + cache + sequential segment playback (Unity-4 API).
- `SRRVoices/VoicePack.cs` — TSV index loader (net35 has no good JSON parser).
- `SRRVoices/BorderlessWindow.cs` — user32 P/Invoke for borderless fullscreen.
