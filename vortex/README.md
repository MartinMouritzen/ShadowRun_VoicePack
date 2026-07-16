# Vortex game extensions (one-click "Mod Manager Download")

These three small [Vortex](https://www.nexusmods.com/about/vortex/) game extensions make the green
**Mod Manager Download** button on each game's Nexus page install the AI Voice Pack in one click —
Vortex deploys the bundle (`winhttp.dll` + `doorstop_config.ini` + `BepInEx/`) straight to the game
root, no prompts.

| Folder | Game | Nexus domain | Steam AppID | Exe |
|---|---|---|---|---|
| `shadowrundragonfall/` | Dragonfall (Director's Cut) | shadowrundragonfall | 300550 | Dragonfall.exe |
| `shadowrunhongkong/`   | Hong Kong (Extended Edition) | shadowrunhongkong | 346940 | SRHK.exe |
| `shadowrunreturns/`    | Shadowrun Returns (Dead Man's Switch) | shadowrunreturns | 234650 | Shadowrun.exe |

Each extension: detects the game on **Steam and GOG** (`GameStoreHelper.findByName`), sets
`queryModPath` so mods deploy correctly, and wires up `modtype-bepinex` for a **32-bit (x86) Unity
Mono** game with **BepInEx bundled** (`autoDownloadBepInEx: false`). Bundling matters: if Vortex
auto-downloaded vanilla BepInEx it would overwrite our custom Camera-entrypoint `BepInEx.cfg` and the
plugin would never load.

## Before publishing: add a logo

Each extension references `gameart.jpg`. Drop the game's cover/header image (a roughly square JPG or
PNG, ~256px) into each folder as `gameart.jpg`. The Steam library capsule works well. The extension
loads without it, but Vortex shows a blank tile.

## Test locally (do this first — these are untested in a live Vortex)

1. In Vortex: **Extensions** (hamburger menu) → drag the extension **folder** (or a zip of it) onto
   the drop area, or use **Install From File**. Restart Vortex when prompted.
2. Vortex → **Games** → the game should appear and auto-detect (Manage it). If not detected, set the
   path manually to the game root.
3. On the game's Nexus page, click **Mod Manager Download** on the voice-pack file → it should install
   and, after **Deploy**, place `winhttp.dll` + `BepInEx/` next to the game exe.
4. Launch the game and confirm voices play (and, for SRR, that any ContentPack mods still deploy to
   `Shadowrun_Data/StreamingAssets/ContentPacks`).

## Publish

Two options per extension:

- **Community extension (fastest):** zip the folder's contents and upload to
  `nexusmods.com/site/mods` under the Vortex "Game (unofficial)" category. Vortex then offers to
  install it when a user opens the game or clicks a Mod Manager Download for that domain.
- **Bundle into Vortex (best reach):** PR the extension to
  [`Nexus-Mods/vortex-games`](https://github.com/Nexus-Mods/vortex-games). Once merged it ships with
  Vortex for everyone, no manual extension install.

## Shadowrun Returns — the conflict note

Vortex already ships an **official** `shadowrunreturns` extension that deploys mods to
`…/ContentPacks` and has no BepInEx handling. Our `shadowrunreturns/` extension uses the **same id**
(required so the `nxm://shadowrunreturns/...` one-click routes to it), so installing it as a community
extension **overrides** the built-in one. It's written as a *superset* — content-pack mods still go to
`ContentPacks`, BepInEx mods go to root — so it shouldn't regress ContentPack users, but test that.

**Preferred long-term route for SRR:** instead of a same-id community extension, PR the official
extension. The entire change is adding these to its `index.js`:

```js
context.requireExtension('modtype-bepinex');          // near the top of main()
// …after context.registerGame({...})…
context.once(() => {
  context.api.ext.bepinexAddGame?.({
    gameId: 'shadowrunreturns',
    autoDownloadBepInEx: false,
    architecture: 'x86',
    unityBuild: 'unitymono',
    doorstopConfig: { doorstopType: 'default' },
  });
});
```

That leaves the built-in ContentPacks behaviour untouched and just adds BepInEx-to-root. Dragonfall
and Hong Kong have no built-in extension, so their folders here are the whole solution.

## Verify the Steam AppIDs / exe names

`300550` (Dragonfall DC), `346940` (Hong Kong), `234650` (Shadowrun Returns), and exe names
`Dragonfall.exe` / `SRHK.exe` / `Shadowrun.exe` are what this repo's install scripts already use, but
double-check against your own installs before publishing.
