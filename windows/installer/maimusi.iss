; Inno Setup script of the Windows installer. Compiled by windows/package.ps1,
; which passes the /D defines below from packaging/product.env and versions.json.
; Identity shown to users: publisher (세반시옷), website and support e-mail only.
;
;   Name, NameEn, Version, Build, Publisher, Website, Email, Copyright,
;   Stage (build\windows\stage\<version>), Icon, License, OutDir, OutName

#define AppGuid "{{5A3FC69E-F538-4A5E-8B84-1D95E112164B}"

[Setup]
AppId={#AppGuid}
AppName={#Name}
AppVersion={#Version}
AppVerName={#Name} {#Version}
AppPublisher={#Publisher}
AppPublisherURL={#Website}
AppSupportURL={#Website}
AppUpdatesURL={#Website}
AppContact={#Email}
AppCopyright={#Copyright}
VersionInfoCompany={#Publisher}
VersionInfoCopyright={#Copyright}
VersionInfoDescription={#Name} 설치 프로그램
VersionInfoProductName={#Name}
VersionInfoProductVersion={#Version}
VersionInfoVersion={#Version}.{#Build}
DefaultDirName={autopf}\{#NameEn}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
PrivilegesRequired=admin
; The text service DLLs are loaded into every application. x64 Windows: x64\ and
; x86\. Windows 11 on Arm: arm64\ (ARM64X, for ARM64 applications and x64
; applications under emulation, which share the 64-bit registry) and x86\.
ArchitecturesAllowed=x64os or arm64
ArchitecturesInstallIn64BitMode=x64os or arm64
MinVersion=10.0.17763
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\{#Version}.{#Build}\MaimusiSettings.exe
UninstallDisplayName={#Name} ({#NameEn})
LicenseFile={#License}
WizardStyle=modern
; Artwork from windows/tools/make_wizard.ps1, one file per display scale.
WizardImageFile={#WizardImages}
WizardSmallImageFile={#WizardSmall}
WizardImageStretch=no
WizardImageBackColor=$10110F
Compression=lzma2/max
SolidCompression=yes
OutputDir={#OutDir}
OutputBaseFilename={#OutName}
; Running applications keep the old DLL until they restart; never close them.
CloseApplications=no
RestartApplications=no
ShowLanguageDialog=no
SetupLogging=no
; Reproducible, machine-neutral output.
TimeStampsInUTC=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Messages]
korean.FinishedLabel=[name] 설치를 마쳤습니다.%n%n작업 표시줄의 입력 표시기(또는 Windows 키 + Space)에서 [name]을(를) 고르면 사용할 수 있습니다. 한/영 키로 한글과 영문을 바꿉니다. 이미 열려 있던 프로그램은 다시 시작해야 새 버전이 적용됩니다.%n%n설정에서 단어장을 내보내거나, 고른 폴더(OneDrive 등)로 다른 PC·Mac과 맞출 수 있습니다.

[Files]
; Each version and build gets its own folder, so an update never has to replace a DLL
; that running applications still have loaded.
Source: "{#Stage}\*"; DestDir: "{app}\{#Version}.{#Build}"; Flags: recursesubdirs createallsubdirs ignoreversion restartreplace uninsrestartdelete

[Icons]
Name: "{autoprograms}\{#Name} 설정"; Filename: "{app}\{#Version}.{#Build}\MaimusiSettings.exe"

[Run]
; 32-bit first: the last registration sets the profile icon to the 64-bit DLL.
; {sys}\regsvr32.exe is the native one (ARM64 on Windows on Arm), which loads
; the ARM64 side of the ARM64X DLL and registers that DLL's own path.
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/s ""{app}\{#Version}.{#Build}\x86\MaimusiTIP.dll"""; Flags: runhidden waituntilterminated; StatusMsg: "입력기를 등록하는 중…"
Filename: "{sys}\regsvr32.exe"; Parameters: "/s ""{app}\{#Version}.{#Build}\x64\MaimusiTIP.dll"""; Flags: runhidden waituntilterminated; Check: not IsArm64
Filename: "{sys}\regsvr32.exe"; Parameters: "/s ""{app}\{#Version}.{#Build}\arm64\MaimusiTIP.dll"""; Flags: runhidden waituntilterminated; Check: IsArm64
Filename: "{app}\{#Version}.{#Build}\MaimusiSettings.exe"; Parameters: "--register-user"; Flags: runhidden waituntilterminated runasoriginaluser
Filename: "{app}\{#Version}.{#Build}\README.txt"; Description: "사용법 보기"; Flags: postinstall shellexec nowait skipifsilent runasoriginaluser unchecked
Filename: "{app}\{#Version}.{#Build}\MaimusiSettings.exe"; Description: "{#Name} 설정 열기"; Flags: postinstall nowait skipifsilent runasoriginaluser unchecked

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im MaimusiEngine.exe"; Flags: runhidden waituntilterminated; RunOnceId: "StopEngine"
Filename: "{app}\{#Version}.{#Build}\MaimusiSettings.exe"; Parameters: "--unregister-user"; Flags: runhidden waituntilterminated; RunOnceId: "UnregisterUser"
Filename: "{sys}\regsvr32.exe"; Parameters: "/s /u ""{app}\{#Version}.{#Build}\x64\MaimusiTIP.dll"""; Flags: runhidden waituntilterminated; RunOnceId: "Unregister64"; Check: not IsArm64
Filename: "{sys}\regsvr32.exe"; Parameters: "/s /u ""{app}\{#Version}.{#Build}\arm64\MaimusiTIP.dll"""; Flags: runhidden waituntilterminated; RunOnceId: "UnregisterArm64"; Check: IsArm64
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/s /u ""{app}\{#Version}.{#Build}\x86\MaimusiTIP.dll"""; Flags: runhidden waituntilterminated; RunOnceId: "Unregister32"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Windows on Arm runs the x64 parts (settings, engine) under emulation, which
// Windows 10 on Arm lacks.
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  Result := (not IsArm64) or (Version.Build >= 22000);
  if not Result then
    SuppressibleMsgBox('ARM64 PC에서는 Windows 11 이상이 필요합니다.', mbCriticalError, MB_OK, IDOK);
end;

// The engine server may be running from this folder; stop it before files are copied.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/f /im MaimusiEngine.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

// False if the file exists and cannot be deleted (an application has it loaded).
function RemovedOrAbsent(const Path: String): Boolean;
begin
  Result := (not FileExists(Path)) or DeleteFile(Path);
end;

// Remove folders of earlier versions (their DLLs are no longer registered).
// Applications started before the update keep using the old text service
// DLL, which needs its engine, model and font next to it: a folder whose DLL
// is still loaded is left whole and removed by a later update.
procedure CurStepChanged(CurStep: TSetupStep);
var
  FindRec: TFindRec;
  Base, Dir: String;
begin
  if CurStep <> ssPostInstall then Exit;
  Base := ExpandConstant('{app}');
  if FindFirst(Base + '\*', FindRec) then
  try
    repeat
      if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and (FindRec.Name <> '.') and
         (FindRec.Name <> '..') and (FindRec.Name <> '{#Version}.{#Build}') then
      begin
        Dir := Base + '\' + FindRec.Name;
        if RemovedOrAbsent(Dir + '\x64\MaimusiTIP.dll') and RemovedOrAbsent(Dir + '\arm64\MaimusiTIP.dll') and
           RemovedOrAbsent(Dir + '\x86\MaimusiTIP.dll') then
          DelTree(Dir, True, True, True);
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;
