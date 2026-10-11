[Setup]
AppId=FXStudio.LocalSoundEffects
AppName=FX Studio
AppVersion=0.1.0
AppPublisher=WIK+DEV
AppPublisherURL=https://wikplus.dev/
DefaultDirName={localappdata}\Programs\FX Studio
DefaultGroupName=FX Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=FXStudio-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\FX Studio.exe

[Files]
Source: "..\dist\FX Studio Windows\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FX Studio"; Filename: "{app}\FX Studio.exe"
Name: "{autodesktop}\FX Studio"; Filename: "{app}\FX Studio.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\FX Studio.exe"; Description: "Launch FX Studio"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := FileExists(ExpandConstant('{sysnative}\msvcp140.dll')) and
            FileExists(ExpandConstant('{sysnative}\VCRUNTIME140_THREADS.dll'));
  if not Result then
  begin
    Log('The latest Microsoft Visual C++ v14 x64 runtime is required for LiteRT.');
    if not WizardSilent then
      if MsgBox('FX Studio needs the latest Microsoft Visual C++ v14 x64 runtime. Install it from Microsoft, then run this installer again.' + #13#10 + #13#10 + 'Open Microsoft''s official download page?', mbInformation, MB_YESNO) = IDYES then
        ShellExec('open', 'https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;
end;
