# Install the SRR AI Voices mod into Shadowrun Returns.
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-GameDir "C:\path\to\Shadowrun Returns"]
# If -GameDir is omitted, tries the default Steam location.
# Copies the assembled dist\ tree into the game root. Idempotent (overwrites plugin + voicepack).
param(
  [string]$GameDir = ""
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$dist = Join-Path $repo "dist"

if (-not (Test-Path $dist)) {
  Write-Error "dist\ not found. Run tools/build_dist.sh first (needs the plugin + voicepack built)."
}

if ($GameDir -eq "") {
  $candidates = @(
    "C:\Program Files (x86)\Steam\steamapps\common\Shadowrun Returns",
    "C:\Program Files\Steam\steamapps\common\Shadowrun Returns"
  )
  foreach ($c in $candidates) { if (Test-Path $c) { $GameDir = $c; break } }
}
if ($GameDir -eq "" -or -not (Test-Path $GameDir)) {
  Write-Error "Game dir not found. Pass -GameDir ""C:\path\to\Shadowrun Returns""."
}
if (-not (Test-Path (Join-Path $GameDir "Shadowrun.exe"))) {
  Write-Warning "Shadowrun.exe not found in $GameDir — is this the right folder?"
}

Write-Host "Installing into: $GameDir"
# Copy everything from dist\ into the game root (winhttp.dll, doorstop, BepInEx\...).
Copy-Item -Path (Join-Path $dist "*") -Destination $GameDir -Recurse -Force

$clips = (Get-ChildItem (Join-Path $GameDir "BepInEx\plugins\SRRVoices\voicepack\clips") -Filter *.ogg -ErrorAction SilentlyContinue).Count
Write-Host "Done. Installed plugin + voicepack ($clips clips)."
Write-Host "Launch the game from Steam. Check BepInEx\LogOutput.log for 'SRR AI Voices ready.'"
Write-Host "To uninstall: delete winhttp.dll, doorstop_config.ini, .doorstop_version, and the BepInEx\ folder."
