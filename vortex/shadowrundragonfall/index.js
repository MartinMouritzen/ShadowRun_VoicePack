// Vortex game extension: Shadowrun: Dragonfall - Director's Cut
// Enables one-click "Mod Manager Download" for BepInEx mods (e.g. the SRR AI Voice Pack).
// Deploys the mod archive to the GAME ROOT (queryModPath '.') and wires up the modtype-bepinex
// integration for a 32-bit (x86) Unity Mono game. BepInEx is BUNDLED inside the mod archive, so
// autoDownloadBepInEx is false (letting Vortex fetch vanilla BepInEx would overwrite the mod's
// custom Camera-entrypoint BepInEx.cfg and the plugin would never load).
const path = require('path');
const { fs, util } = require('vortex-api');

const GAME_ID = 'shadowrundragonfall';   // MUST equal the nexusmods.com domain for nxm:// one-click
const STEAMAPP_ID = '300550';
const EXEC = 'Dragonfall.exe';

function findGame() {
  return util.GameStoreHelper
    .findByName(["Shadowrun: Dragonfall - Director's Cut", 'Shadowrun Dragonfall Directors Cut', 'Shadowrun Dragonfall'])
    .then(game => game.gamePath);
}

function prepareForModding(discovery) {
  // ensure the plugins dir exists so a plugin-only mod has somewhere to land
  return fs.ensureDirWritableAsync(path.join(discovery.path, 'BepInEx', 'plugins'));
}

function main(context) {
  context.requireExtension('modtype-bepinex');
  context.registerGame({
    id: GAME_ID,
    name: "Shadowrun: Dragonfall (Director's Cut)",
    mergeMods: true,
    queryPath: findGame,
    queryModPath: () => '.',            // deploy to the game root (BepInEx lives at root)
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
        autoDownloadBepInEx: false,      // the mod bundles its own tested BepInEx + config
        architecture: 'x86',
        unityBuild: 'unitymono',
        doorstopConfig: { doorstopType: 'default' },   // winhttp.dll hook (correct for Unity 4/5)
      });
    }
  });
  return true;
}

module.exports = { default: main };
