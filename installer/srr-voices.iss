; Inno Setup script for the Shadowrun AI Voice Pack — one double-click installer per game.
; Parameterized via ISCC /D defines (see tools/build_installer.sh):
;   GameId    dms | dragonfall | hk
;   GameName  display name, e.g. "Shadowrun Returns"
;   GameExe   Shadowrun.exe | Dragonfall.exe | SRHK.exe
;   SteamAppId  234650 | 300550 | 346940
;   DistDir   absolute path to the built dist/<game> tree (contains winhttp.dll, BepInEx\, ...)
;   AppVersion  e.g. 1.1
;   OutDir    where to write the compiled Setup .exe
;
; The installer auto-detects the game folder from Steam's per-app uninstall registry key
; (InstallLocation), falls back to a folder picker, verifies the game exe is present, and copies the
; self-contained bundle (BepInEx loader + plugin + voicepack) into the game root.

#ifndef GameName
  #define GameName "Shadowrun Returns"
#endif
#ifndef GameExe
  #define GameExe "Shadowrun.exe"
#endif
#ifndef SteamAppId
  #define SteamAppId "234650"
#endif
#ifndef GameId
  #define GameId "dms"
#endif
#ifndef AppVersion
  #define AppVersion "1.1"
#endif
#ifndef DistDir
  #define DistDir "..\dist\dms"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

[Setup]
AppId={{com.mmo.srrvoices.{#GameId}}
AppName={#GameName} — AI Voice Pack
AppVersion={#AppVersion}
AppPublisher=MartinMouritzen
DefaultDirName={code:DetectGameDir}
DisableProgramGroupPage=yes
DisableWelcomePage=no
UsePreviousAppDir=yes
DirExistsWarning=no
AllowNoIcons=yes
OutputDir={#OutDir}
OutputBaseFilename=ShadowRun_VoicePack_{#GameId}_v{#AppVersion}_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=
UninstallDisplayName={#GameName} — AI Voice Pack
UninstallDisplayIcon={app}\{#GameExe}

[Messages]
WelcomeLabel2=This will install the AI Voice Pack into your {#GameName} folder.%n%nMake sure the folder shown on the next screen is your {#GameName} install (the one containing {#GameExe}).

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Code]
function SteamAppDir(): String;
var
  loc: String;
  key: String;
begin
  Result := '';
  key := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {#SteamAppId}';
  { Steam writes a per-app uninstall entry with InstallLocation. From a 32-bit installer, HKLM is
    redirected to WOW6432Node, but Steam often writes the key to the 64-bit view — so check HKLM64
    first, then the 32-bit view, then native. }
  if RegQueryStringValue(HKLM64, key, 'InstallLocation', loc) then
    Result := loc
  else if RegQueryStringValue(HKLM32, key, 'InstallLocation', loc) then
    Result := loc
  else if RegQueryStringValue(HKLM, key, 'InstallLocation', loc) then
    Result := loc;
end;

function DetectGameDir(Param: String): String;
var dir: String;
begin
  dir := SteamAppDir();
  if (dir <> '') and FileExists(AddBackslash(dir) + '{#GameExe}') then
    Result := dir
  else
    Result := ExpandConstant('{autopf}');   { fallback: Program Files; user picks the real folder }
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if not FileExists(AddBackslash(WizardDirValue()) + '{#GameExe}') then
    begin
      if MsgBox('{#GameExe} was not found in:' + #13#10 + WizardDirValue() + #13#10#13#10 +
                'This does not look like your {#GameName} folder. Install here anyway?',
                mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;
