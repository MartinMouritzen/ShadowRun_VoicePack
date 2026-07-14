# Shadowrun Returns AI Voice — BepInEx Playback Plugin: Implementation Plan

**Audience:** an implementing agent (Opus 4.8) with no prior context on this project.
**Goal:** a BepInEx plugin that, while playing *Shadowrun Returns (Dead Man Switch)*, plays the
pre-generated AI voice clips as each dialogue line appears on screen — narrator segments and
character segments in the correct order.

This document is self-contained. Everything you need (hook point, data model, file layout,
audio format, fullscreen) is below. Do not re-derive; verify against the cited files if unsure.

---

## 0. Current state (what already exists)

A "voice lab" web app has been used to cast voices and generate/select audio takes for
Dead Man Switch. The relevant outputs live under `/home/mmo/dev/shadowrun-voices/`:

- `app/data/characters.json` — every character + every dialogue line (with conversation id + node index).
- `app/data/line_segments.json` — **the authoritative playback model.** For each line that contains
  `{{GM}}` narration or is a narration node, an **ordered** list of segments:
  `{ "<convoId>_<nodeIndex>": [ {"who":"gm","t":"..."}, {"who":"char","t":"..."}, ... ] }`.
  Lines NOT in this file are plain single-speaker character lines (one segment, the whole node).
- `app/data/takes.json` — generated takes per segment, with the **selected keeper**:
  `{ "<charId>": { "<segKey>": { "selected": "<relpath>.mp3", "takes":[{file,voiceId,voiceName,...}] } } }`
  - `charId` is `"narrator"` for GM/narration segments, else `name_<slug>` (e.g. `name_dresden`).
  - `segKey`: for a single-speech line it's `"<convoId>_<nodeIndex>"`. For a multi-segment line
    it's `"<convoId>_<nodeIndex>~g<i>"` (i-th narration segment, voiced by narrator) or
    `"~c<i>"` (i-th character speech segment). `<i>` counts only within that who-type, in order.
  - `selected` is the keeper file, relative to `app/audio/`.
- `app/data/picks.json` — chosen voice per character (informational; plugin doesn't need it).
- `app/data/spoken_overrides.json`, `directed.json`, `text_edits.json` — the *script* actually
  spoken can differ from on-screen text ($()-variable rewrites, `[emotion]` tags). **The plugin
  does not care** — it only plays audio files keyed by segment; the text-to-audio mapping was
  already resolved at generation time.
- `app/audio/<charId>/takes/<segKey>__<voice>__<ts>.mp3` — the actual audio. **MP3, 44.1kHz.**

**Audio format problem:** takes are MP3. Unity 4 standalone `WWW.GetAudioClip` reliably decodes
**OGG and WAV, NOT MP3** (confirmed by the community `SRAssetPatcherPlugin`). So the export step
(Part A) MUST transcode to OGG Vorbis. `ffmpeg` is available.

---

## 1. Target game & engine facts (verified)

- **Game dir:** `/mnt/c/Program Files (x86)/Steam/steamapps/common/Shadowrun Returns/`
  (Windows: `C:\Program Files (x86)\Steam\steamapps\common\Shadowrun Returns\`). Steam appid 234650.
  Data dir: `Shadowrun_Data/`. Managed assemblies: `Shadowrun_Data/Managed/`.
- **Engine:** Unity **4.2.0f4**, **Mono** backend, **32-bit (x86)**. (Dragonfall DC = 4.3.4, Hong
  Kong = 4.6.2 — out of scope now; the same plugin design ports to them later.)
- **Loader:** **BepInEx 5.4.23.2, win_x86** (the Mono branch). BepInEx 5 bundles **HarmonyX 2.10.2**.
- **CRITICAL BepInEx config:** old Unity needs a non-default entrypoint or it never loads the
  preloader and the game crashes/does nothing. In `BepInEx/config/BepInEx.cfg` set:
  ```
  [Preloader.Entrypoint]
  Assembly = UnityEngine.dll
  Type = Camera
  Method = .cctor
  ```
  This is the documented Unity-5-and-older workaround; the community Shadowrun plugins all use it.
- **Reference DLLs for the plugin project** (copy locally, do NOT ship):
  `Shadowrun_Data/Managed/Assembly-CSharp.dll` (all game logic),
  `Shadowrun_Data/Managed/ShadowrunDTO.dll` (data types incl. `isogame.Conversation`,
  `isogame.ConversationNode`, `isogame.IDRef`), `UnityEngine.dll`.
- **Community precedent** (working BepInEx plugins for these exact games; use as reference):
  - `lynnpye/SRPluginTemplate` (GitHub) — the plugin template; SRR plugin = Nexus mod 270.
  - `lynnpye/SRAssetPatcherPlugin` — proves runtime audio-from-disk (WAV/OGG) injection works here.
  - Target framework: **.NET 3.5** (`net35`). Mono/Unity 4 era.

---

## 2. The hook point (verified by decompiling Assembly-CSharp.dll)

Class **`ConversationManager`** (a `MonoBehaviour`, singleton-ish; there is one active instance
while a conversation is on screen). Key members (decompiled signatures):

```csharp
private Conversation thisConvoDef;                 // field @ line 82 — the running conversation
public void StartConversation(Conversation convoDef, Player player,
                              Player ownerPlayer=null, Prop ownerProp=null, bool ownerFacePlayer=false); // ~977
public void EndConversation();                     // ~1064
private void ShowNodeText(ConversationNode node, Player thisSpeaker);  // ~440  <-- PRIMARY HOOK
```

`ShowNodeText` is called once for **every dialogue node as it is displayed**. Inside it:
`string text = ContentStrings.T(node.text);` and it branches on `node.nodeType`
(`ConversationNodeType_GM_Voice`=4, `_GM_Speaker_Voice`=6, input types 7/8, `_Simple`=1).

**What the hook needs to identify the line:**
- **Conversation id:** `thisConvoDef.idRef.id` (a private field on the instance — read via Harmony
  `AccessTools`/`Traverse`). `isogame.Conversation.idRef` is ProtoMember 1; `IDRef.id` is a string
  (24-hex, e.g. `51ace200303031b413002718`). This equals the `<convoId>` used in the data files.
- **Node index:** `node.index` (`isogame.ConversationNode.index`, public int). This equals `<nodeIndex>`.

So the runtime key for a displayed node is **`<thisConvoDef.idRef.id>_<node.index>`** — exactly the
base `segKey` in the data. 

Recommended Harmony patch: **Postfix on `ShowNodeText`** (play audio after the UI updates its text),
with a Prefix optional if you want to stop a previous clip immediately. Signature for the patch:
```csharp
[HarmonyPatch(typeof(ConversationManager), "ShowNodeText")]
static void Postfix(ConversationManager __instance, ConversationNode node, Player thisSpeaker) { ... }
```
Get `thisConvoDef` via `AccessTools.Field(typeof(ConversationManager),"thisConvoDef").GetValue(__instance)`
then read `.idRef.id`. (Both `Conversation` and `IDRef` are public types in ShadowrunDTO.dll, so you
can cast and read directly.)

Also **Postfix `EndConversation`** → stop/clear any playing VO.
Optionally **Postfix `StartConversation`** → preload that conversation's clips (see Part C).

**Continue/advance behavior:** the game shows one node, waits for the player to click Continue,
then shows the next node (calls `ShowNodeText` again). So audio should:
- On each `ShowNodeText`, **stop the previous line's audio** and start the new line's sequence.
- If a line has multiple ordered segments (narrator→char→…), play them back-to-back via a coroutine.
- Do NOT block the game / auto-advance; the player still controls Continue. If they click Continue
  mid-VO, the next `ShowNodeText` fires and your patch stops the old clip and starts the new one.
  (That's the correct, non-intrusive behavior — matches subtitles today.)

---

## 3. Segment ordering & audio lookup (the core mapping)

For a displayed node with key `K = "<convoId>_<node.index>"`, build the ordered clip list:

1. **If `line_segments.json` has key `K`:** it lists ordered segments. Walk them, tracking two
   counters `gi` and `ci` (start 0). For each segment:
   - `who=="gm"`  → look under `takes["narrator"]["K~g" + gi]`, then `gi++`.
   - `who=="char"`→ look under `takes[<lineCharId>][segKey]` where `segKey = K` if the line has
     exactly one char segment, else `"K~c" + ci`; then `ci++`.
   - Use the `selected` keeper file for that segKey. Skip segments with no selected take.
2. **If `K` is not in `line_segments.json`:** plain single line. Look under
   `takes[<lineCharId>][K].selected`. (Also check `takes["narrator"][K]` — pure GM_Voice narration
   nodes are stored under narrator with plain key.)

**`<lineCharId>`** = the character that owns the line. The export step (Part A) resolves this once
and bakes it into the manifest, so the plugin never re-derives it. **Do not make the plugin read the
lab's raw JSON** — Part A produces a flat, plugin-friendly `voicepack.json`.

### The plugin's real input: `voicepack.json` (produced by Part A)
```json
{
  "version": 1,
  "game": "srr-dms",
  "lines": {
    "<convoId>_<nodeIndex>": ["clips/<sha1>.ogg", "clips/<sha1>.ogg"],   // ordered
    ...
  }
}
```
Value = ordered list of ogg paths (relative to the voicepack root) to play in sequence for that
node. Narrator-vs-character is already encoded as order; the plugin does not need who-info.
Only lines with at least one selected keeper appear. This keeps the plugin dead-simple: look up the
node key, play the list in order.

---

## PART A — Export step (tool, runs offline; Python, ffmpeg)

Write `tools/build_voicepack.py` in the repo. It:
1. Loads `characters.json`, `line_segments.json`, `takes.json`.
2. For each line that has any selected take across its segments, resolves the **ordered** keeper
   files using the counter logic in §3 (this logic already exists in JS in `app/lab.html`
   `segsFor()` + take-key derivation — mirror it exactly; single-char-segment lines use the plain
   key, multi use `~c<i>`, narration uses `~g<i>` under `narrator`).
3. Transcodes each unique selected MP3 → OGG Vorbis with ffmpeg:
   `ffmpeg -i in.mp3 -c:a libvorbis -q:a 5 -ar 44100 out.ogg` (mono is fine: add `-ac 1`).
   Name each `clips/<sha1-of-source-relpath>.ogg` to dedupe identical takes.
4. Writes `voicepack/voicepack.json` (schema in §3) + `voicepack/clips/*.ogg`.
5. Prints coverage: how many nodes have audio, total clips, total MB.

Output dir: `voicepack/` (this is what ships in the mod's release, dropped into the plugin's
config folder — see Part D). Keep it deterministic (no timestamps in names) so re-exports are stable.

---

## PART B — BepInEx plugin project

Create `plugin/SRRVoices/` — a C# class library, `net35`, x86.

**`SRRVoices.csproj`** essentials:
- `<TargetFramework>net35</TargetFramework>`, `<PlatformTarget>x86</PlatformTarget>`.
- References (HintPath into the game's Managed dir + BepInEx core, all `Private=false`):
  `BepInEx.dll`, `0Harmony.dll`, `UnityEngine.dll`, `Assembly-CSharp.dll`, `ShadowrunDTO.dll`.
- Follow `lynnpye/SRPluginTemplate`'s csproj for exact relative-reference wiring; it's designed for
  exactly this and handles the game-dir path.

**`Plugin.cs`** — `[BepInPlugin("com.mmo.srrvoices","SRR AI Voices","1.0.0")]`,
`BaseUnityPlugin`, in `Awake()`:
- Load `voicepack.json` from the plugin's data dir (see Part D) into `Dictionary<string,string[]>`.
- Create a persistent `GameObject` (DontDestroyOnLoad) with one `AudioSource`
  (`playOnAwake=false`, `spatialBlend=0` i.e. 2D, `ignoreListenerPause=true`,
  `volume = configVolume`).
- `Harmony harmony = new Harmony("com.mmo.srrvoices"); harmony.PatchAll();`
- Read config (BepInEx `Config.Bind`): `Volume` (0–1, default 0.9), `Enabled` (bool),
  `BorderlessFullscreen` (bool, default false — see Part E), `DuckMusic` (bool, optional).

**`ConversationPatches.cs`** — the Harmony patches from §2. On `ShowNodeText` Postfix:
```
key = convoIdFrom(__instance) + "_" + node.index;
if (voicepack.TryGetValue(key, out clips)) VoicePlayer.PlaySequence(clips);
else VoicePlayer.StopAll();     // no VO for this node → ensure silence
```
On `EndConversation` Postfix → `VoicePlayer.StopAll()`.

**`VoicePlayer.cs`** — the audio engine (a MonoBehaviour on the persistent GameObject):
- `PlaySequence(string[] relPaths)`: stop current, start a coroutine that for each path:
  loads the clip (Part C), `audioSource.clip = clip; audioSource.Play();`
  `yield return new WaitWhile(() => audioSource.isPlaying);` then next.
- `StopAll()`: stop coroutine + `audioSource.Stop()`.
- A generation counter / token so a new `PlaySequence` cancels the old coroutine cleanly.

---

## PART C — Loading OGG clips in Unity 4 (the tricky bit)

Unity 4 has **no `UnityWebRequest`**. Use legacy `WWW`:
```csharp
string url = "file://" + fullPath.Replace("\\","/");   // fullPath = plugin data dir + relPath
WWW w = new WWW(url);
yield return w;                                          // wait for load
AudioClip clip = w.GetAudioClip(false /*3D*/, false /*stream*/, AudioType.OGGVORBIS);
// (Unity 4 signature may be w.audioClip; if AudioType overload is missing, .oggVorbis/.audioClip works for .ogg)
while (clip.loadState != AudioDataLoadState.Loaded && !clip.isReadyToPlay) yield return null;
```
Notes / gotchas:
- Unity 4 `WWW.GetAudioClip` overloads vary; on 4.2 `w.audioClip` (property) returns an OGG clip for a
  `file://….ogg` URL. Test both; prefer the property if the typed overload isn't present.
- **file:// URLs must use forward slashes** and URL-encode spaces (the game path has spaces:
  `Program Files (x86)`). Encode the path or (better) install the voicepack under a space-free dir
  (see Part D) to avoid escaping pain.
- **Preload to avoid hitches:** on `StartConversation` Postfix, read that conversation's node keys
  (`thisConvoDef.nodes` → each `.index`), look up their clip lists, and kick off `WWW` loads into a
  small `Dictionary<string,AudioClip>` cache. Conversations are small (tens of nodes), so a
  conversation's worth of OGG fits easily. Evict on `EndConversation`. This makes per-line playback
  instant. If preloading is too fiddly for v1, on-demand load per line is acceptable (minor first-play
  hitch); ship on-demand first, add preloading if it stutters.
- Consider `AudioClip.loadType` isn't controllable via WWW; that's fine at this scale.

---

## PART D — Packaging / install layout

The mod ships as: BepInEx (x86) + the plugin DLL + the voicepack. Recommended install:
```
<game>/
  winhttp.dll                         (BepInEx bootstrapper)
  BepInEx/
    config/BepInEx.cfg                (with the Camera entrypoint set — Part 1)
    plugins/SRRVoices/
      SRRVoices.dll
      voicepack/
        voicepack.json
        clips/*.ogg
```
The plugin resolves its data dir via `Paths.PluginPath` + `"SRRVoices/voicepack"` (BepInEx `Paths`),
so it works regardless of the game's absolute path. This also sidesteps the `file://` space-encoding
issue if you still encode, but prefer to `Uri`-escape the full path anyway.

Provide an **installer** (a small `install.ps1` or a documented drag-drop) that:
1. Copies BepInEx win_x86 5.4.23.2 into the game dir.
2. Writes/patches `BepInEx.cfg` with the Camera entrypoint (idempotent).
3. Copies `SRRVoices/` (dll + voicepack) into `BepInEx/plugins/`.

Distribution channels (already decided with the user): **GitHub** (canonical, releases carry the
voicepack) + **Nexus Mods** mirror. Estimated full-campaign voicepack size ~0.3–0.4 GB as mono OGG.
Ship only generated audio + our code — never game files or extracted script text. Steam Workshop is
NOT viable (it only distributes editor content packs, cannot install DLLs).

---

## PART E — Borderless fullscreen (user asked for this; include as a config toggle)

Two options, ship both:
1. **Zero-code:** Steam launch option `-popupwindow` + set in-game resolution = desktop resolution,
   fullscreen off. Document this. Works on Unity 4 out of the box.
2. **In-plugin (config `BorderlessFullscreen=true`):** on startup, force it so the user needn't fiddle:
   - `Screen.SetResolution(desktopW, desktopH, false);` (windowed at desktop size), then
   - Strip the window chrome via user32 P/Invoke on the Unity HWND:
     `GetActiveWindow()` (or `FindWindow` by the Unity window class/title) →
     `SetWindowLong(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE)` → `SetWindowPos(hwnd, 0,0,0, w,h, ...)`.
   - `Display.main` / `Screen.currentResolution` gives desktop size.
   Guard with `#if` for Windows only; this game is Windows-first for the mod.

---

## PART F — Testing (how the user verifies it actually works)

**There is no in-game audio until this plugin exists.** Once built:
1. Export a partial voicepack covering the **opening conversations** (see §Opening below) so there's
   something to hear immediately without generating all 3,253 lines.
2. Install per Part D onto the real game.
3. **Launch the game from Steam** and start a new game / reach the first conversation.
4. **Verify by ear + eye** (per the user's hard rule — a running window, not logs): the dialogue box
   appears AND the matching clip plays; multi-segment lines play narrator-then-character in order;
   clicking Continue cuts the old clip and starts the next; ending the conversation stops audio.
5. Check `BepInEx/LogOutput.log` for load errors, missing-clip warnings, and Harmony patch success.
   Add a plugin log line per played key (`[SRRVoices] play <key> (<n> clips)`) and per miss.
6. Confirm no MP3s slipped through (all clips OGG); confirm no stutter (add preload if needed).
7. Test borderless fullscreen toggle.

**Build/verify loop from WSL:** you can invoke Windows tooling from WSL — MSBuild/`dotnet` for the
csproj, and launch the game exe — but the **visual/audio confirmation must be a human at the running
game** (the project's standing rule: never mark a render/UX gate passed without eyes/ears on it).

---

## Opening conversations (for pre-generating the first ~20 lines)

The user wants to generate the first ~20 dialogues before running. Determining exact play order:
- Scenes carry the campaign order; scene files: `dead_man_switch/data/scenes/*.srt.bytes`, named by
  chapter: `c01-s1_3yearsago`, `c02-s1_morgue`, `c03-s1_barrens`, `c04-s1_seamstress`,
  `c05-s2_pikeplace`, `c06-s1_aptsfirstfloor`, … (c01 = prologue flashback with Sam; c02 = morgue,
  meet **Dresden**; c03 = Barrens; c04 = Seamstresses; …).
- Conversation `ui_name` carries the scene prefix, e.g. `c02-s1_Morgue_Dresden01`. So grouping
  conversations by `c01`,`c02`,… prefix (available in `characters.json` line `cn` field) gives play
  order closely enough. The narrated **intro/animatic** text and the **c01–c03** conversations are
  the first the player hears.
- Practical recipe for the first ~20: in the lab, generate every segment of the conversations whose
  `cn` starts `c01`, `c02`, `c03` (Dresden's morgue intro is the very first substantial dialogue).
  A helper could dump, for each scene prefix in order, the conversation list and node counts — a
  `tools/opening_order.py` that reads `characters.json`, filters by `cn` prefix, and prints the
  conversations in `c01…c03` with their line counts. (Not yet written — trivial add.)
- Exact runtime order within a scene is trigger-driven and not fully static, but "voice all of
  c01–c03" guarantees the opening is covered regardless of branch.

---

## Risks / open items (call out, don't silently swallow)

1. **Unity 4 `WWW` OGG decode overload uncertainty** — the exact `GetAudioClip`/`audioClip` API on
   4.2.0f4 must be confirmed at build time against the real `UnityEngine.dll`. Fallback: WAV export
   (`ffmpeg -c:a pcm_s16le`) which `WWW` definitely decodes, at a size cost.
2. **`thisConvoDef` private-field access** — confirmed present (line 82); read via reflection/Traverse.
   If a build strips it, fall back to reading the convo id from `StartConversation`'s `convoDef` arg
   (patch StartConversation, stash `convoDef.idRef.id` in a field, use it in ShowNodeText).
3. **MP3 in voicepack would silently fail** — the export MUST transcode; assert no `.mp3` ships.
4. **Speaker attribution for unvoiced/unattributed lines** — 177 lines are in an "unattributed"
   bucket and won't have audio; the plugin just plays nothing for those (subtitle only). Fine for v1.
5. **Preload memory** — if a conversation is unusually large, cap the cache; on-demand load is the
   safe default.
6. **Do NOT auto-advance dialogue to match audio length** — leave player pacing untouched; audio
   yields to the next `ShowNodeText`.

---

## Deliverables checklist

- [ ] `tools/build_voicepack.py` (Part A) — MP3→OGG, ordered manifest, coverage report.
- [ ] `tools/opening_order.py` — prints c01–c03 conversations for pre-generation.
- [ ] `plugin/SRRVoices/` csproj (net35/x86) + `Plugin.cs` + `ConversationPatches.cs` + `VoicePlayer.cs`.
- [ ] BepInEx.cfg Camera-entrypoint documented + set by installer.
- [ ] `install.ps1` (or documented manual install) per Part D.
- [ ] Borderless-fullscreen config toggle (Part E).
- [ ] In-game verification by the user (Part F) — the only acceptable "it works".

## Key file references (verified this session)
- Hook: `ConversationManager.ShowNodeText(ConversationNode, Player)` in
  `Shadowrun_Data/Managed/Assembly-CSharp.dll` (decompile to confirm signatures).
- Convo id at runtime: `ConversationManager.thisConvoDef.idRef.id`; node index: `ConversationNode.index`.
- DTO types in `ShadowrunDTO.dll`: `isogame.Conversation` (idRef=PM1, ui_name=PM2, nodes=PM3),
  `isogame.ConversationNode` (idRef=PM1, index=PM2, text=PM4, branches=PM5, nodeType=PM6),
  `isogame.IDRef` (id=PM1, string).
- Data the plugin consumes: `app/data/{characters,line_segments,takes}.json` → distilled by Part A
  into `voicepack/voicepack.json`.
- `ilspycmd` for decompiling (installed): `DOTNET_ROLL_FORWARD=Major ~/.dotnet/tools/ilspycmd -t <Type> <dll>`.
