# Shadowrun Trilogy: AI Voice Packs

Full AI-generated voice acting for the **Shadowrun Returns trilogy** — three isolated voice packs, one per game:

| Pack | Game | Content packs |
|---|---|---|
| **Dead Man's Switch** | Shadowrun Returns | `dead_man_switch` |
| **Dragonfall** | Shadowrun: Dragonfall — Director's Cut | `DragonfallExtended` |
| **Hong Kong** | Shadowrun: Hong Kong — Extended Edition | `HongKong` + `hk_coda` (bonus campaign) |

A BepInEx plugin plays voiced dialogue, narration, inspect one-liners, terminal readouts, and combat barks in-game. A companion "Voice Lab" web app (a single tabbed shell across all three games) is used to cast voices and generate/audition every line.

Each game is shipped as **its own release / Nexus mod** — same repo, separate distributions.

> Fan project. Not affiliated with Harebrained Schemes or Paradox. Shadowrun is a trademark of its respective owners. This repo contains the tooling, data, and plugin; the generated audio is distributed as separate per-game releases.

## What it does

- **Every cast character speaks**, including the narrator game-wide (all `{{GM}}` narration, even inside un-cast characters' lines).
- **Inspect one-liners** ("examine object" descriptions) are voiced by the narrator.
- **Combat barks** (lines actors shout in a fight) are voiced per speaker.
- **Terminals / machines** use local Windows SAPI voices (David / Zira / Mark) for a synthetic feel, at zero API cost.
- Segmented lines play in order (narrator, then character) with a natural beat between voice swaps.
- Config toggles to enable/disable inspect voicing and combat-bark voicing independently (both default on), plus a borderless-fullscreen toggle.

## Repo layout

| Path | What |
|---|---|
| `plugin/SRRVoices/` | The BepInEx 5 (win_x86) plugin: conversation/inspect/bark Harmony patches, OGG streaming voice player, borderless window. `bin/SRRVoices.dll` is the built plugin (shared across all three games — the ShadowrunDTO schema is identical). |
| `app/` | The Voice Lab: `server.py` (game-aware ElevenLabs + Magnific generation, take management), `lab.html` (character casting), `barks.html` (combat barks), `nav.js` (shared game/view top-nav). |
| `app/data/<game>/` | Per-game content + casting state: `characters.json`, `barks.json`, `inspect.json`, `scene_actors.json`, `picks.json`, `takes.json`, `line_segments.json`, etc. `<game>` is `dms`, `dragonfall`, or `hk`. |
| `app/data/` (root) | Shared voice catalog + ElevenLabs account state: `el_voices.json`, `magnific_voices.json`, `protected_voices.json`, `voice_slots.json`. |
| `app/audio/<game>/` | Per-game generated take audio (not in git). |
| `tools/` | Extraction (`extract_game.py`, `extract_extras_game.py`), per-game voicepack build (`build_voicepack.py <game>`), per-game install (`sync_to_game.sh <game>`, `build_dist.sh <game>`, `install.ps1 -Game <game>`). |
| `voicepack/<game>/` | Per-game `voicepack.index` / `voicepack.json` manifests (the OGG clips ship in each game's Release). |
| `docs/` | Plugin plan and notes. |

## Voice Lab

Run `python3 app/server.py [port]` (default 3717) and open `lab.html`. The top nav switches between the three games and between the **Characters** and **Combat Barks** views; the active game is carried in the `?game=` query param. The ElevenLabs/Magnific voice catalog is shared across all three games; casting, takes, and generated audio are isolated per game.

## Mapping a game's conversations

```
python3 tools/extract_game.py        "<ContentPacks dir>" app/data/<game> <pack1[,pack2,...]>
python3 tools/extract_extras_game.py "<ContentPacks dir>" app/data/<game> <pack1[,pack2,...]>
```

`extract_game.py` writes `characters.json` (attributed dialogue). `extract_extras_game.py` writes `barks.json`, `inspect.json`, and `scene_actors.json`. Char sheets are read from all packs; conversations/scenes only from the listed packs. Example for Hong Kong: `... "<...>/SRHK_Data/StreamingAssets/ContentPacks" app/data/hk HongKong,hk_coda`.

All three games are already mapped. Both extractors **refuse to overwrite existing output** (pass `--force` to re-map) so a re-run can't destroy the manual attribution corrections layered onto `app/data/dms/` (Tweaker split, Ghoul→Jake, Player-1, etc.).

## Building & installing a pack (per game)

```
bash tools/build_voicepack.py <game>   # export selected takes -> voicepack/<game>/
bash tools/build_dist.sh      <game>   # assemble dist/<game>/ (BepInEx + plugin + voicepack)
powershell -File tools/install.ps1 -Game <game>   # install into the game folder
```

Or, from the running lab, hit **⇩ Sync to game** — it runs `sync_to_game.sh <game>` for the active game.

`plugin/build.sh` compiles the plugin against the game's managed DLLs + HarmonyX via the Windows `csc.exe`. Output: `plugin/SRRVoices/bin/SRRVoices.dll`.

## Notes

- Voices generated at ElevenLabs `eleven_v3` stability 0 (Creative) for expressiveness, with retakes where needed.
- The generated audio (raw takes + OGG voicepack) is **not** in git; grab it from each game's Release.
- No API keys are included. `server.py` reads a local `.elevenlabs.key` (gitignored).
