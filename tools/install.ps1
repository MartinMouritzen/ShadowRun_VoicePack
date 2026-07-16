# Install an SRR AI Voices pack into its game (isolated per game).
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Game dms [-GameDir "C:\path\to\game"]
#   -Game : dms | dragonfall | hk   (default dms)
# If -GameDir is omitted, tries the default Steam location for that game.
# Copies the assembled dist\<game>\ tree into the game root. Idempotent (overwrites plugin + voicepack).
param(
  [ValidateSet("dms","dragonfall","hk")]
  [string]$Game = "dms",
  [string]$GameDir = ""
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$dist = Join-Path $repo (Join-Path "dist" $Game)

if (-not (Test-Path $dist)) {
  Write-Error "dist\$Game not found. Run: bash tools/build_dist.sh $Game (needs the plugin + voicepack built)."
}

# Per-game default Steam locations + the exe used to sanity-check the folder.
$steam = "C:\Program Files (x86)\Steam\steamapps\common"
$defaults = @{
  dms        = @{ dir = "$steam\Shadowrun Returns";                     exe = "Shadowrun.exe" }
  dragonfall = @{ dir = "$steam\Shadowrun Dragonfall Director's Cut";   exe = "Dragonfall.exe" }
  hk         = @{ dir = "$steam\Shadowrun Hong Kong";                   exe = "SRHK.exe" }
}
$info = $defaults[$Game]

if ($GameDir -eq "") {
  if (Test-Path $info.dir) { $GameDir = $info.dir }
}
if ($GameDir -eq "" -or -not (Test-Path $GameDir)) {
  Write-Error "Game dir not found. Pass -GameDir ""$($info.dir)""."
}
if (-not (Test-Path (Join-Path $GameDir $info.exe))) {
  Write-Warning "$($info.exe) not found in $GameDir - is this the right folder?"
}

Write-Host "Installing $Game pack into: $GameDir"
# Copy everything from dist\<game>\ into the game root (winhttp.dll, doorstop, BepInEx\...).
Copy-Item -Path (Join-Path $dist "*") -Destination $GameDir -Recurse -Force

$clips = (Get-ChildItem (Join-Path $GameDir "BepInEx\plugins\SRRVoices\voicepack\clips") -Filter *.ogg -ErrorAction SilentlyContinue).Count
Write-Host "Done. Installed $Game plugin + voicepack ($clips clips)."
Write-Host "Launch the game from Steam. Check BepInEx\LogOutput.log for 'SRR AI Voices ready.'"
Write-Host "To uninstall: delete winhttp.dll, doorstop_config.ini, .doorstop_version, and the BepInEx\ folder."
