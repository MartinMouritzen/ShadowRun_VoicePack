# Nexus upload — how the pack ships

The whole thing is **one ZIP**. For a game with built-in Vortex support (Shadowrun Returns), the
green "Mod Manager Download" button works in **stock Vortex with no custom extension and no PR** — the
ZIP carries a `dinput8.dll` marker that triggers Vortex's built-in, game-agnostic "dinput" installer,
which deploys the archive to the game root (copy-only: it does not rewrite our BepInEx config and does
not rename the mod). See the comment in `tools/build_dist.sh` — the marker is load-bearing, keep it.

Only **Dead Man's Switch** is voiced right now, so it's the only mod page to publish.

## The file

| File | Where | Purpose |
|---|---|---|
| `ShadowRun_VoicePack_DMS_v1.2.zip` | `dist/` (build with `tools/build_dist.sh dms` then zip `dist/dms/`) | The one and only download — Vortex one-click **and** manual extract. |

### NOT distributed on Nexus
- **`*_Setup.exe` (Inno Setup installer).** Nexus flags/rejects `.exe` uploads regardless, so it is
  not a Nexus download. The ZIP already covers Vortex + manual, so it isn't needed. `build_installer.sh`
  still works for off-Nexus distribution (e.g. a GitHub release), but don't upload it to Nexus.
- **The Vortex game extension in `vortex/`.** Superseded by the `dinput8.dll` marker for SRR — not
  needed. (It stays in the repo only as reference / a possible path for Dragonfall+HK, which have no
  built-in Vortex support; see the bottom note.)

## Publish / update the Dead Man's Switch mod

On **nexusmods.com/shadowrunreturns**, Files tab:

1. Upload **`ShadowRun_VoicePack_DMS_v1.2.zip`** as a **Main file**, version **1.2**.
   **Leave "manual download only" UNCHECKED** — the marker makes the green button work, so you want it on.
2. **Archive any older ZIP** (e.g. v1.1) — older ZIPs lack the marker, so their Vortex button is broken.
3. Bump the mod version to match.

### Draft mod description

> **AI Voice Pack — Shadowrun Returns (Dead Man's Switch)**
>
> Full AI voice acting for the entire Dead Man's Switch campaign. Every cast character speaks, the
> narrator reads all scene descriptions game-wide, "examine" one-liners are voiced, and terminals use
> synthetic voices. Over 3,900 hand-picked lines.
>
> **Install — either way:**
> - **Vortex (one click):** click *Mod Manager Download*. Accept the one-time "this mod contains a
>   .dll, continue?" prompt. Deploy, launch, done. (Works on stock Vortex — no extra setup.)
> - **Manual:** download the ZIP and extract its contents into your Shadowrun Returns folder (the one
>   with `Shadowrun.exe`) — you'll end up with `winhttp.dll` and a `BepInEx` folder next to it.
>
> Options (volume, toggle inspect/bark voicing, borderless fullscreen) are in
> `BepInEx/config/com.mmo.srrvoices.cfg` after first launch. Self-contained — bundles BepInEx.
>
> *Fan project. Not affiliated with Harebrained Schemes or Paradox.*

## Verify the one-click for real (recommended before flipping it on for everyone)

Against a **vanilla** Shadowrun Returns folder (no mod files, game managed by Vortex's built-in
extension — no custom extension installed):

1. On the Nexus page, click **Mod Manager Download** on the ZIP → **Continue** on the .dll prompt.
2. Vortex → **Mods** → enable → **Deploy**.
3. Confirm `winhttp.dll` + `dinput8.dll` + `BepInEx/` land next to `Shadowrun.exe` (not in
   `ContentPacks`), the `BepInEx.cfg` entrypoint is still `UnityEngine.dll / Camera / .cctor`, and the
   mod keeps its real name (not "Bepis Injector Extensible").
4. Launch via Steam → voices.

## Pushing updates later (optional automation)

`.github/workflows/nexus-upload.yml` can push a new ZIP version to the existing file via Nexus's
official upload-action (needs the `NEXUS_API_KEY` repo secret + the file's `file_id`). The Upload API
can only **update an existing file** — it cannot create the mod page, edit the description, or upload
media. Those stay manual.

## Dragonfall / Hong Kong (future)

Not voiced yet. When they are: they have **no** built-in Vortex extension, so the `dinput8.dll` marker
alone won't make Vortex recognise the game — those two would need the `vortex/` game extension
published as a community extension (nexusmods.com/site/mods) for Vortex to manage them at all. The
manual ZIP always works regardless. Build their packs with `tools/build_dist.sh dragonfall|hk`.
