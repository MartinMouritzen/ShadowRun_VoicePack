// Vortex game extension: Shadowrun: Dragonfall - Director's Cut
// Deploys BepInEx mods to the game root. The AI Voice Pack bundles the full BepInEx loader, which
// Vortex's built-in modtype-bepinex installer (priority 10) would rename to "Bepis Injector
// Extensible". We claim our archive first with a lower-priority installer (5) that deploys to root
// via our own modType without a customFileName attribute, so the mod keeps its Nexus name.
const path = require('path');
const { fs, util } = require('vortex-api');

const GAME_ID = 'shadowrundragonfall';   // MUST equal the nexusmods.com domain for nxm:// one-click
const STEAMAPP_ID = '300550';
const EXEC = 'Dragonfall.exe';
const MODTYPE_VOICEPACK = 'srrvoices-voicepack';
const SIG = 'bepinex/plugins/srrvoices/';

function findGame() {
  return util.GameStoreHelper
    .findByName(["Shadowrun: Dragonfall - Director's Cut", 'Shadowrun Dragonfall Directors Cut', 'Shadowrun Dragonfall'])
    .then(game => game.gamePath);
}

function prepareForModding(discovery) {
  return fs.ensureDirWritableAsync(path.join(discovery.path, 'BepInEx', 'plugins'));
}

function main(context) {
  context.requireExtension('modtype-bepinex');

  context.registerGame({
    id: GAME_ID,
    name: "Shadowrun: Dragonfall (Director's Cut)",
    mergeMods: true,
    queryPath: findGame,
    queryModPath: () => '.',            // deploy to the game root
    logo: 'gameart.jpg',
    executable: () => EXEC,
    requiredFiles: [EXEC],
    setup: prepareForModding,
    environment: { SteamAPPId: STEAMAPP_ID },
    details: { steamAppId: parseInt(STEAMAPP_ID, 10) },
  });

  const getGameRoot = (game) => {
    const state = context.api.getState();
    const discovery = state.settings.gameMode.discovered[game.id];
    return (discovery !== undefined) ? discovery.path : undefined;
  };
  context.registerModType(MODTYPE_VOICEPACK, 25,
    (gameId) => gameId === GAME_ID,
    getGameRoot,
    () => Promise.resolve(false),
    { mergeMods: true, name: 'SRR AI Voice Pack' });

  context.registerInstaller('srrvoices-voicepack', 5,
    (files, gameId) => {
      const ok = (gameId === GAME_ID)
        && files.some(f => f.replace(/\\/g, '/').toLowerCase().indexOf(SIG) !== -1);
      return Promise.resolve({ supported: ok, requiredFiles: [] });
    },
    (files) => {
      const instructions = files
        .filter(f => !f.endsWith('/') && !f.endsWith('\\'))
        .map(f => ({ type: 'copy', source: f, destination: f }));
      instructions.push({ type: 'setmodtype', value: MODTYPE_VOICEPACK });
      return Promise.resolve({ instructions });
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
