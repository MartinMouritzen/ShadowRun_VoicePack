# Shadowrun Returns: AI Voice Pack

Full AI-generated voice acting for **Shadowrun Returns** (the *Dead Man's Switch* campaign). A BepInEx plugin plays voiced dialogue, narration, inspect one-liners, and terminal readouts in-game, with a companion "Voice Lab" web app used to cast voices and generate/audition every line.

> Fan project. Not affiliated with Harebrained Schemes or Paradox. Shadowrun is a trademark of its respective owners. This repo contains the tooling, data, and plugin; the generated audio is distributed as a separate release.

## What it does

- **Every cast character speaks** across Dead Man's Switch, including the narrator game-wide (all `{{GM}}` narration, even inside un-cast characters' lines).
- **Inspect one-liners** ("examine object" descriptions) are voiced by the narrator.
- **Terminals / machines** (accounting terminal, medical board, Lone Star database, etc.) use local Windows SAPI voices (David / Zira / Mark) for a synthetic feel, at zero API cost.
- **Borderless fullscreen** toggle.
- Segmented lines play in order (narrator, then character) with a natural beat between voice swaps.

## Repo layout

| Path | What |
|---|---|
| `plugin/SRRVoices/` | The BepInEx 5 (win_x86) plugin: conversation/inspect Harmony patches, OGG streaming voice player, borderless window. `bin/SRRVoices.dll` is the built plugin. |
| `app/` | The Voice Lab: `server.py` (ElevenLabs + Magnific generation, take management) and `lab.html` (casting UI). |
| `app/data/` | All project data: extracted `characters.json`, per-character `picks.json` / `char_notes.json` (voice directions), `line_segments.json`, `text_edits.json`, `inspect.json`, `takes.json`. |
| `tools/` | Extraction (`extract_dms.py`), voicepack build (`build_voicepack.py`), generation, and `sync_to_game.sh`. |
| `voicepack/` | `voicepack.index` / `voicepack.json` manifests (the OGG clips ship in the Release). |
| `docs/` | Plugin plan and notes. |

## Installing (players)

1. Install **BepInEx 5.4.x (x86)** into your Shadowrun Returns folder.
2. Copy `SRRVoices.dll` into `BepInEx/plugins/SRRVoices/`.
3. Download the **voicepack** from the Releases page and extract it to `BepInEx/plugins/SRRVoices/voicepack/`.
4. Launch. Config (volume, segment gap, borderless) is in `BepInEx/config/com.mmo.srrvoices.cfg`.

## Building the plugin

`plugin/build.sh` compiles against the game's managed DLLs + HarmonyX via the Windows `csc.exe`. Output: `plugin/SRRVoices/bin/SRRVoices.dll`.

## Notes

- Voices generated at ElevenLabs `eleven_v3` stability 0 (Creative) for expressiveness, with retakes where needed.
- The generated audio (raw takes ~500MB, OGG voicepack ~270MB) is **not** in git; grab it from Releases.
- No API keys are included. `server.py` reads a local `.elevenlabs.key` (gitignored).
