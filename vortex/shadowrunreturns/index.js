// Vortex game extension: Shadowrun Returns (BepInEx-aware SUPERSET of the built-in extension)
//
// Vortex already ships an official 'shadowrunreturns' extension whose queryModPath is
// Shadowrun_Data/StreamingAssets/ContentPacks (correct for content-pack mods) but which has NO
// BepInEx handling. This extension keeps the content-pack behaviour AND adds BepInEx support so the
// AI Voice Pack deploys to the game root.
//
// The voice pack bundles the full BepInEx loader (winhttp.dll + BepInEx/core) so it installs in one
// step. Vortex's built-in modtype-bepinex installer (priority 10) would recognise that as "the
// BepInEx framework" and rename the mod to "Bepis Injector Extensible". To avoid that, we register
// our OWN installer at a LOWER priority (5) that claims our specific archive first (it contains
// BepInEx/plugins/SRRVoices/), deploys the tree to the game root via our own modType, and does NOT
// emit a customFileName attribute — so the mod keeps its Nexus name.
const path = require('path');
const { fs, util } = require('vortex-api');

const GAME_ID = 'shadowrunreturns';   // MUST equal the nexusmods.com domain for nxm:// one-click
const STEAMAPP_ID = '234650';
const EXEC = 'Shadowrun.exe';
const CONTENTPACKS = path.join('Shadowrun_Data', 'StreamingAssets', 'ContentPacks');
const MODTYPE_VOICEPACK = 'srrvoices-voicepack';
// our archive's unique signature (normalised to forward slashes, lower-case)
const SIG = 'bepinex/plugins/srrvoices/';

function findGame() {
  return util.GameStoreHelper.findByName(['Shadowrun Returns']).then(game => game.gamePath);
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

  // deploy target for OUR modType = the game root
  const getGameRoot = (game) => {
    const state = context.api.getState();
    const discovery = state.settings.gameMode.discovered[game.id];
    return (discovery !== undefined) ? discovery.path : undefined;
  };
  // our modType: files deploy to the game root; no name override so the Nexus name is kept.
  // priority 25 is the extension-author range; assignment is explicit via our installer (test = false).
  context.registerModType(MODTYPE_VOICEPACK, 25,
    (gameId) => gameId === GAME_ID,
    getGameRoot,
    () => Promise.resolve(false),
    { mergeMods: true, name: 'SRR AI Voice Pack' });

  // claim OUR archive before the built-in BepInEx injector (priority 10) so it isn't renamed.
  context.registerInstaller('srrvoices-voicepack', 5,
    (files, gameId) => {
      const ok = (gameId === GAME_ID)
        && files.some(f => f.replace(/\\/g, '/').toLowerCase().indexOf(SIG) !== -1);
      return Promise.resolve({ supported: ok, requiredFiles: [] });
    },
    (files) => {
      const instructions = files
        .filter(f => !f.endsWith('/') && !f.endsWith('\\'))   // skip directory entries
        .map(f => ({ type: 'copy', source: f, destination: f }));
      instructions.push({ type: 'setmodtype', value: MODTYPE_VOICEPACK });
      return Promise.resolve({ instructions });
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
