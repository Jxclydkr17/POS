; ============================================================
; Violette POS — Inno Setup Installer Script
; ============================================================
; Requisito: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
;
; USO:
;   1. Compilar el .exe con: build.bat
;   2. Compilar el instalador con:
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;      (build.bat lo hace automáticamente pasando la versión)
;
; RESULTADO:
;   Output/ViolettePOS_Setup_X.Y.Z.exe
; ============================================================

#define MyAppName "Violette POS"
; Fix 3.2: La versión se recibe desde build.bat via /DMyAppVersion=X.Y.Z
; Si no se pasa, usa el fallback hardcodeado (solo para compilación manual).
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "Violette"
#define MyAppExeName "ViolettePOS.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=ViolettePOS_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Icono del instalador
; SetupIconFile=ui\assets\logo.ico

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el &Escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "quicklaunchicon"; Description: "Crear acceso directo en la &barra de tareas"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
; Todo el contenido de dist/ViolettePOS/
Source: "dist\ViolettePOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; .env template (no sobreescribir si ya existe de una instalacion anterior)
Source: ".env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Ejecutar la app despues de instalar (opcional)
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpiar archivos generados en runtime (NUNCA borrar *.db — son datos del usuario)
Type: filesandordirs; Name: "{app}\*.log"
Type: filesandordirs; Name: "{app}\session.json"
Type: filesandordirs; Name: "{app}\data\pdfs"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// Crear directorios necesarios post-instalacion
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(ExpandConstant('{app}\data\backups'));
    ForceDirectories(ExpandConstant('{app}\data\pdfs'));
    ForceDirectories(ExpandConstant('{app}\certs'));
  end;
end;
