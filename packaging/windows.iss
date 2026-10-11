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
