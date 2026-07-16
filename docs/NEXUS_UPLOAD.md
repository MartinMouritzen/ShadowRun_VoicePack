# Nexus upload & Vortex one-click — step by step

Everything a release needs to go live on Nexus with a one-click Vortex install. Only **Dead Man's
Switch** is voiced right now, so it's the only mod page to publish yet; the Vortex extensions for all
three games can be published whenever.

## Files (built by this repo)

| File | Where | Purpose |
|---|---|---|
| `ShadowRun_VoicePack_DMS_v1.1.zip` | GitHub release v1.1 / `dist/` | **Vortex + manual.** The archive Vortex extracts to the game root; manual users extract it themselves. |
| `ShadowRun_VoicePack_DMS_v1.1_Setup.exe` | GitHub release v1.1 / `dist/` | **Double-click installer** for people who don't use a mod manager. |
| `dist/vortex-extensions/vortex-shadowrunreturns.zip` | `dist/vortex-extensions/` | The Vortex game extension that makes the green button one-click for SRR. |
| …`vortex-shadowrundragonfall.zip`, `vortex-shadowrunhongkong.zip` | same | Same, for the other two games (publish when they have a mod). |

## A. Publish the Dead Man's Switch mod

On **nexusmods.com/shadowrunreturns** → *Add a mod*:

1. **Files tab — upload both** (each gets its own green "Mod Manager Download" button):
   - `ShadowRun_VoicePack_DMS_v1.1.zip` as a **Main file**. This is the one Vortex deploys — its top level is `winhttp.dll` + `doorstop_config.ini` + `BepInEx/`, which the BepInEx modtype routes to the game root. Do **not** tick "manual download only."
   - `ShadowRun_VoicePack_DMS_v1.1_Setup.exe` as a **Main file** (or Miscellaneous). This is the double-click installer for non-Vortex users. (Vortex can't deploy a raw .exe, so Vortex users should use the ZIP.)
2. **Description** — draft below.
3. **Requirements** — none (BepInEx is bundled).

### Draft mod description

> **AI Voice Pack — Shadowrun Returns (Dead Man's Switch)**
>
> Full AI voice acting for the entire Dead Man's Switch campaign. Every cast character speaks, the
> narrator reads all scene descriptions game-wide, "examine" one-liners are voiced, and terminals use
> synthetic voices. Over 3,900 hand-picked lines.
>
> **Install — pick one:**
> - **Vortex (one-click):** click *Mod Manager Download* on the ZIP. (First time on this game, Vortex
>   will offer to install the "Shadowrun Returns" support extension — accept it.) Deploy, launch, done.
> - **Installer:** download the `_Setup.exe`, run it — it finds your game folder automatically.
> - **Manual:** download the ZIP and extract its contents into your Shadowrun Returns folder (the one
>   with `Shadowrun.exe`).
>
> Options (volume, toggle inspect/bark voicing, borderless fullscreen) are in
> `BepInEx/config/com.mmo.srrvoices.cfg` after first launch. Self-contained — bundles BepInEx.
>
> *Fan project. Not affiliated with Harebrained Schemes or Paradox.*

## B. Publish the Vortex extension (enables the one-click)

Without a Vortex game extension for the game's Nexus domain, the green button can't deploy. Two ways:

- **Fast — community extension:** upload `vortex-shadowrunreturns.zip` to **nexusmods.com/site/mods**
  (the "Vortex" site) under **Vortex → Games (unofficial)**. Vortex then offers to install it when a
  user opens a Mod Manager Download for `shadowrunreturns`.
- **Best reach — PR:** submit the extension to
  [`Nexus-Mods/vortex-games`](https://github.com/Nexus-Mods/vortex-games); once merged it ships with
  Vortex for everyone. For **SRR specifically**, prefer PR-ing the *existing* `game-shadowrunreturns`
  extension (just add the two BepInEx lines — see `vortex/README.md`) rather than shipping a same-id
  community extension that overrides it. Dragonfall/HK are greenfield — new extensions.

## C. Test the Vortex one-click end to end (you)

Do this against a **vanilla** Shadowrun Returns folder (the isolated-test state).

1. **Vortex → Extensions** (hamburger) → *Install From File* → pick
   `dist/vortex-extensions/vortex-shadowrunreturns.zip` → restart Vortex.
2. **Vortex → Games** → find **Shadowrun Returns** → *Manage*. It should auto-detect the folder
   (Steam or GOG); if not, point it at the game root.
3. On the DMS Nexus page, click **Mod Manager Download** on the **ZIP** file.
4. Vortex → **Mods** → enable the mod → **Deploy**.
5. Confirm `winhttp.dll` + `BepInEx/` now sit next to `Shadowrun.exe`, launch the game, hear voices.
6. (SRR only) sanity-check that any ContentPack mod still deploys to
   `Shadowrun_Data/StreamingAssets/ContentPacks` — the extension is a superset, not a replacement.

If step 2 or 3 misbehaves, check `vortex/README.md` (Steam/GOG IDs, the built-in-extension conflict
note) and report back.

## Dragonfall / Hong Kong

Their Vortex extensions and installer/dist tooling are ready, but there are **no voices generated
yet**, so hold their Nexus mod pages until the packs are built (`tools/build_dist.sh dragonfall|hk`
after casting). Publishing their Vortex extensions early is harmless if you want the game support in
place first.
