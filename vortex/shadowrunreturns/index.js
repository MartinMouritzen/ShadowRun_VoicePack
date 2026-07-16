// Vortex game extension: Shadowrun Returns (BepInEx-aware SUPERSET of the built-in extension)
//
// Vortex already ships an official 'shadowrunreturns' extension whose queryModPath is
// Shadowrun_Data/StreamingAssets/ContentPacks (correct for content-pack mods) but which has NO
// BepInEx handling — so a BepInEx mod pushed through it lands in ContentPacks and never loads.
//
// This extension keeps that content-pack behaviour AND adds the modtype-bepinex integration. The
// bepinex modType resolves to the GAME ROOT independently of queryModPath, so:
//   * content-pack mods  -> Shadowrun_Data/StreamingAssets/ContentPacks   (unchanged)
//   * BepInEx-structured mods (winhttp.dll + BepInEx/) -> game root         (new: the voice pack)
// both coexist.
//
// NOTE: it registers the same game id ('shadowrunreturns') as the built-in extension, so it will
// override it. If you also manage ContentPack mods through Vortex, the cleaner long-term route is a
// PR to Nexus-Mods/vortex-games adding the two BepInEx lines to the official extension (see
// vortex/README.md). For users who just want the AI Voice Pack, installing this gives one-click.
const path = require('path');
const { fs, util } = require('vortex-api');

const GAME_ID = 'shadowrunreturns';   // MUST equal the nexusmods.com domain for nxm:// one-click
const STEAMAPP_ID = '234650';
const EXEC = 'Shadowrun.exe';
const CONTENTPACKS = path.join('Shadowrun_Data', 'StreamingAssets', 'ContentPacks');

function findGame() {
  return util.GameStoreHelper
    .findByName(['Shadowrun Returns'])
    .then(game => game.gamePath);
}

function prepareForModding(discovery) {
  return fs.ensureDirWritableAsync(path.join(discovery.path, 'BepInEx', 'plugins'))
    .then(() => fs.ensureDirWritableAsync(path.join(discovery.path, CONTENTPACKS)));
}

function main(context) {
  context.requireExtension('modtype-bepinex');
  context.registerGame({
    id: GAME_ID,
    name: 'Shadowrun Returns',
    mergeMods: true,
    queryPath: findGame,
    queryModPath: () => CONTENTPACKS,   // default modType (content packs) — matches the built-in
    logo: 'gameart.jpg',
    executable: () => EXEC,
    requiredFiles: [EXEC],
    setup: prepareForModding,
    environment: { SteamAPPId: STEAMAPP_ID },
    details: { steamAppId: parseInt(STEAMAPP_ID, 10) },
  });
  context.once(() => {
    if (context.api.ext.bepinexAddGame !== undefined) {
      context.api.ext.bepinexAddGame({
        gameId: GAME_ID,
        autoDownloadBepInEx: false,      // the voice pack bundles its own BepInEx + Camera config
        architecture: 'x86',
        unityBuild: 'unitymono',
        doorstopConfig: { doorstopType: 'default' },
      });
    }
  });
  return true;
}

module.exports = { default: main };
