; Instalador de MixMaster. Se compila con construir.ps1 (arma build\ primero).
; Se instala en la carpeta del usuario: no pide permisos de administrador y la app puede guardar su config.

[Setup]
AppName=MixMaster
AppVersion=0.5
AppPublisher=Bruno
DefaultDirName={localappdata}\Programs\MixMaster
DefaultGroupName=MixMaster
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=salida
OutputBaseFilename=MixMaster-Instalador
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
Compression=lzma2
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear acceso directo en el escritorio"

[Files]
Source: "build\MixMaster\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "build\modelos\hf\*"; DestDir: "{%USERPROFILE}\.cache\huggingface\hub"; Flags: onlyifdoesntexist recursesubdirs createallsubdirs uninsneveruninstall

[Icons]
Name: "{autoprograms}\MixMaster"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"
Name: "{autodesktop}\MixMaster"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Tasks: escritorio

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "Abrir MixMaster"; Flags: postinstall nowait skipifsilent
