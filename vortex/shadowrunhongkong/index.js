// Vortex game extension: Shadowrun: Hong Kong - Extended Edition
// See the Dragonfall extension for the full rationale. Same pattern: deploy to game root,
// modtype-bepinex x86 / Unity Mono, BepInEx bundled (autoDownloadBepInEx false).
const path = require('path');
const { fs, util } = require('vortex-api');

const GAME_ID = 'shadowrunhongkong';   // MUST equal the nexusmods.com domain for nxm:// one-click
const STEAMAPP_ID = '346940';
const EXEC = 'SRHK.exe';

function findGame() {
  return util.GameStoreHelper
    .findByName(['Shadowrun: Hong Kong - Extended Edition', 'Shadowrun Hong Kong', 'Shadowrun: Hong Kong'])
    .then(game => game.gamePath);
}

function prepareForModding(discovery) {
  return fs.ensureDirWritableAsync(path.join(discovery.path, 'BepInEx', 'plugins'));
}

function main(context) {
  context.requireExtension('modtype-bepinex');
  context.registerGame({
    id: GAME_ID,
    name: 'Shadowrun: Hong Kong',
    mergeMods: true,
    queryPath: findGame,
    queryModPath: () => '.',
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
        autoDownloadBepInEx: false,
        architecture: 'x86',
        unityBuild: 'unitymono',
        doorstopConfig: { doorstopType: 'default' },
      });
    }
  });
  return true;
}

module.exports = { default: main };
