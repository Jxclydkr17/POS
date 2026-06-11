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
; ── FASE 4 — Fix 4.3: Directorio de instalación writable ──
; Antes: {autopf} = C:\Program Files (read-only para usuarios normales).
; La app no podía escribir .env, SQLite DB, PDFs ni backups.
; Ahora: {localappdata} = C:\Users\<user>\AppData\Local\Violette POS
; (siempre writable, estándar para apps modernas como VS Code, Discord).
; NOTA: Si ya tenés una instalación anterior en C:\Program Files,
; copiá manualmente .env y violette_pos.db al nuevo directorio.
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=ViolettePOS_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Ya no se requiere admin: la app se instala en espacio del usuario.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ── FASE 6 — Actualización in-place (auto-update silencioso) ──
; CloseApplications=yes → si algún archivo a reemplazar está en uso, Windows
;   usa el Restart Manager para cerrar la app. Es una RED DE SEGURIDAD: el
;   actualizador integrado ya cierra Violette POS antes de lanzar este
;   instalador, pero esto cubre el caso de que el cierre no haya terminado, o
;   de que el usuario ejecute el instalador con la app abierta.
; RestartApplications=no → NO dejar que el Restart Manager relance la app: del
;   relanzamiento nos encargamos nosotros (ver [Run] para la instalación
;   interactiva y [Code] ssDone para la silenciosa). Así evitamos un doble
;   arranque.
CloseApplications=yes
RestartApplications=no

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

; FASE 3.3: NO creamos `.env` aquí. Antes esta sección copiaba
; `.env.example` -> `.env`, dejando `DB_ENGINE=sqlite` pre-sembrado, por lo
; que el wizard de selección de base de datos (SQLite/MySQL) NUNCA aparecía
; en el primer arranque. Ahora el `.env` lo crea el wizard según la elección
; del usuario. La plantilla `.env.example` ya viaja dentro de
; `dist\ViolettePOS\` (se incluye en el .spec) y llega a {app} por la línea de
; arriba, así que el wizard puede sembrar el `.env` a partir de ella.
;
; Nota: en una reinstalación sobre una instalación previa, el `.env` existente
; se conserva (no se toca aquí), preservando la elección de base de datos.

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Iniciar la app después de una instalación INTERACTIVA (primer install o
; update manual). skipifsilent lo omite en /VERYSILENT a propósito: en ese
; caso (update automático) el relanzamiento lo hace [Code] ssDone, evitando
; un doble arranque.
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpiar archivos generados en runtime (NUNCA borrar *.db — son datos del usuario)
Type: filesandordirs; Name: "{app}\*.log"
Type: filesandordirs; Name: "{app}\session.json"
Type: filesandordirs; Name: "{app}\data\pdfs"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// Crear directorios necesarios post-instalacion
// ── FASE 2 — Fix 2.2: todos los dirs persistentes bajo {app}\data\ ──
// El backend ahora escribe cert/logo/PDFs en {app}\data\... que sobrevive
// updates. Antes el installer creaba {app}\certs (huérfano: backend
// escribía a {app}\_internal\app\certs, borrado en cada update).
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(ExpandConstant('{app}\data\backups'));
    ForceDirectories(ExpandConstant('{app}\data\pdfs'));
    ForceDirectories(ExpandConstant('{app}\data\certs'));
    ForceDirectories(ExpandConstant('{app}\data\uploads\logos'));
    ForceDirectories(ExpandConstant('{app}\data\uploads\purchases'));
  end;

  // ── FASE 6 — Relanzar la app tras una actualización SILENCIOSA ──
  // En instalación interactiva, el [Run] postinstall (con skipifsilent) lanza
  // la app cuando el usuario termina el asistente. En instalación silenciosa
  // —la que dispara el actualizador integrado con /VERYSILENT— ese [Run] se
  // omite, así que relanzamos aquí. WizardSilent() es True solo en /SILENT o
  // /VERYSILENT, por lo que NUNCA hay doble arranque (interactiva = [Run],
  // silenciosa = este Exec). ewNoWait: no bloquear el cierre del instalador.
  if CurStep = ssDone then
  begin
    if WizardSilent() then
      Exec(ExpandConstant('{app}\{#MyAppExeName}'), '', '', SW_SHOW, ewNoWait, ResultCode);
  end;
end;
