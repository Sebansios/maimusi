# Development only: copy build\windows\stage\<version> to a fresh folder under
# build\windows\dev\ and point the input method at it, so a rebuilt DLL never
# collides with a copy that running applications still have loaded.
#   -Elevated : full registration (regsvr32, needs administrator; first time)
#   otherwise : per-user COM override in HKCU (no administrator) after a first -Elevated run
param([switch]$Elevated)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$version = (Get-Content "$Root\versions.json" -Raw | ConvertFrom-Json).product
$stage = "$Root\build\windows\stage\$version"
$dest = "$Root\build\windows\dev\$(Get-Date -Format 'MMdd-HHmmss')"
New-Item -ItemType Directory -Force $dest | Out-Null
Get-ChildItem $stage | Where-Object Name -ne 'engine' | Copy-Item -Destination $dest -Recurse
$engine = "$Root\build\windows\engine\dist\MaimusiEngine"
if (-not (Test-Path "$dest\engine") -and (Test-Path "$engine\MaimusiEngine.exe")) {
    # Junction, not a copy: the engine is large and is not loaded into applications.
    cmd /c mklink /J "$dest\engine" "$engine" | Out-Null
}
$clsid = '{1A36DDCD-E1AE-4B54-AAF1-EF5418F4B25B}'
# The 64-bit DLL: ARM64X on Windows on Arm (this shell may itself be x64 under emulation).
$native = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment').PROCESSOR_ARCHITECTURE
$dll64 = if ($native -eq 'ARM64') { "$dest\arm64\MaimusiTIP.dll" } else { "$dest\x64\MaimusiTIP.dll" }
# First: --register-user also removes per-user COM overrides, including the one written below.
$proc = Start-Process "$dest\MaimusiSettings.exe" -ArgumentList '--register-user' -Wait -PassThru
if ($Elevated) {
    $cmd = "& `"$env:windir\SysWOW64\regsvr32.exe`" /s `"$dest\x86\MaimusiTIP.dll`"; " +
           "& `"$env:windir\System32\regsvr32.exe`" /s `"$dll64`""
    Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile', '-Command', $cmd
} else {
    foreach ($view in @(@{ key = "HKCU:\Software\Classes\CLSID\$clsid\InprocServer32"; dll = $dll64 },
                        @{ key = "HKCU:\Software\Classes\WOW6432Node\CLSID\$clsid\InprocServer32"; dll = "$dest\x86\MaimusiTIP.dll" })) {
        New-Item -Force $view.key | Out-Null
        Set-ItemProperty $view.key -Name '(default)' -Value $view.dll
        Set-ItemProperty $view.key -Name 'ThreadingModel' -Value 'Apartment'
    }
}
Write-Host "dev install: $dest"
