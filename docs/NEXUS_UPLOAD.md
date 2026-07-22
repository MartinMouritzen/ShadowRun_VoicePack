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
| `ShadowRun_VoicePack_DMS_v1.4.zip` | `dist/` (build with `tools/build_dist.sh dms` then zip `dist/dms/`) | The one and only download — Vortex one-click **and** manual extract. Includes the optional AI portrait pack. |

### NOT distributed on Nexus
- **`*_Setup.exe` (Inno Setup installer).** Nexus flags/rejects `.exe` uploads regardless, so it is
  not a Nexus download. The ZIP already covers Vortex + manual, so it isn't needed. `build_installer.sh`
  still works for off-Nexus distribution (e.g. a GitHub release), but don't upload it to Nexus.
- **The Vortex game extension in `vortex/`.** Superseded by the `dinput8.dll` marker for SRR — not
  needed. (It stays in the repo only as reference / a possible path for Dragonfall+HK, which have no
  built-in Vortex support; see the bottom note.)

## Publish / update the Dead Man's Switch mod

On **nexusmods.com/shadowrunreturns**, Files tab:

1. Upload **`ShadowRun_VoicePack_DMS_v1.4.zip`** as a **Main file**, version **1.4**.
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

## Automated upload — `tools/nexus_upload.py` (THIS is what works)

**Use this. It uploads and publishes a release with one command, no website clicking, no GitHub
release, no Actions.** It is generic — pass `--mod-id` / `--domain` to target any of our mods.

```bash
python3 tools/nexus_upload.py dist/ShadowRun_VoicePack_DMS_v1.4.zip 1.4 \
  "Voice Pack v1.4 (Dead Man's Switch)" "<change notes>"
# other games: add  --mod-id <v3ModId> --domain <game>
```

The Nexus API key lives in `games/shadowrun/.nexus.key` (gitignored). The mod's **v3 id** (not the
site id in the URL) is found with:

```bash
KEY=$(cat .nexus.key)
curl -s -H "apikey: $KEY" https://api.nexusmods.com/v3/games/<domain>/mods/<siteModId> | jq .data.id
```

For Shadowrun Returns DMS: site mod id **282**, v3 mod id **438086664474** (baked in as the default).

### Why the GitHub `nexus-upload.yml` workflow never worked

The official `Nexus-Mods/upload-action` only **appends a version** to an existing *v3* mod-file
(`POST /mod-files/{id}/versions`). Every file we uploaded through the website (v1.0–v1.3) is a
**legacy** file that does not exist in the v3 store, so the append always 404'd — including the
"v1.3 release" run. v1.3 actually went up via a **manual website upload** right after that failure.
The `file_id 438086665162` the workflow docs recorded was a **version id**, not a mod-file id, and
it 404s. The workflow is effectively dead; `nexus_upload.py` replaces it.

### What the v3 upload flow actually is (baked into the script)

1. `POST /uploads/multipart {filename, size_bytes}` → `upload_id`, 50 MB `part_size_bytes`,
   `part_presigned_urls[]`, `complete_presigned_url`.
2. `PUT` each part to its presigned R2 URL; keep the returned **ETag with the quotes stripped**.
3. `POST` the `complete_presigned_url` with a `<CompleteMultipartUpload>` XML of `PartNumber`+`ETag`.
4. `POST /uploads/{upload_id}/finalise`, then **poll** `GET /uploads/{upload_id}` until
   `state == "available"` (the S3 complete alone leaves it "processing"; creating before it's
   available fails with "invalid state").
5. `POST /v3/mod-files` with `{upload_id, mod_id (string!), name, version, file_category:"main",
   archive_existing_file, allow_mod_manager_download, update_mod_version}` → **201 Created**.

Gotchas that cost real time, so don't rediscover them: `mod_id` must be a **string**; ETags must be
**unquoted** in the XML; uploads are **single-use** (a failed create needs a fresh upload); and there
is a **finalise + poll** step between the S3 complete and the create.

### The one manual step: archiving the previous version

`archive_existing_file:true` only archives a prior version **within the same file container**. Because
each run *creates a new* mod-file, the previous release stays visible as a second "Main" file. The v3
API exposes **no standalone archive** operation. So after a release, archive the old one by hand:
Nexus → mod **Files** tab → edit the previous version → set category **Archived**. (v1.4 shows on top
regardless, so this is cosmetic, not load-bearing.) Future work: appending to the same container to
auto-archive would remove this step, but create-then-archive is what we have working today.

## Dragonfall / Hong Kong (future)

Not voiced yet. When they are: they have **no** built-in Vortex extension, so the `dinput8.dll` marker
alone won't make Vortex recognise the game — those two would need the `vortex/` game extension
published as a community extension (nexusmods.com/site/mods) for Vortex to manage them at all. The
manual ZIP always works regardless. Build their packs with `tools/build_dist.sh dragonfall|hk`.
