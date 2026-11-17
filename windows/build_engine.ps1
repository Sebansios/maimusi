# Freeze the CharTec (Kiwi) engine server with PyInstaller:
# build\windows\engine\dist\MaimusiEngine\MaimusiEngine.exe (+ _internal).
# Windows counterpart of macos/build_engine.sh. Requires a Python with
# engine\requirements.lock. -Refiner: directory with boundary-refiner.npz to
# bundle (only a model cleared for redistribution, see docs/LICENSING.md).
param([Parameter(Mandatory)][string]$Python, [string]$Refiner = '')
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$Work = "$Root\build\windows\engine"
& python "$Root\tools\versions.py" check
if ($LASTEXITCODE) { throw 'version check failed' }
$V = @{}
foreach ($line in [IO.File]::ReadAllLines("$Root\packaging\version.env")) {
    if ($line -match '^([A-Z_]+)="(.*)"$') { $V[$Matches[1]] = $Matches[2] }
}
$P = @{}
foreach ($line in [IO.File]::ReadAllLines("$Root\packaging\product.env", [Text.Encoding]::UTF8)) {
    if ($line -match '^([A-Z_]+)="(.*)"$') { $P[$Matches[1]] = $Matches[2] }
}
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Force $Work | Out-Null

Write-Host '== engine tests'
$env:PYTHONPATH = "$Root\engine"
$env:PYTHONDONTWRITEBYTECODE = '1'
& $Python -m pytest -q -p no:cacheprovider "$Root\engine\tests" | Select-Object -Last 1
if ($LASTEXITCODE) { throw 'engine tests failed' }

# Version resource of the executable (publisher only, no personal data).
$ev = $V.ENGINE_VERSION.Split('.') + $V.VERSION_BUILD
$tuple = ($ev | ForEach-Object { [int]$_ }) -join ', '
[IO.File]::WriteAllText("$Work\version_info.txt", @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($tuple), prodvers=($tuple), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('041204b0', [
      StringStruct('CompanyName', '$($P.PUBLISHER_KO)'),
      StringStruct('FileDescription', '$($P.PRODUCT_NAME_KO) $($P.ENGINE_NAME_KO) 엔진'),
      StringStruct('FileVersion', '$($V.ENGINE_VERSION).$($V.VERSION_BUILD)'),
      StringStruct('LegalCopyright', 'Copyright © $($P.COPYRIGHT_YEAR) $($P.PUBLISHER_KO)'),
      StringStruct('ProductName', '$($P.PRODUCT_NAME_KO)'),
      StringStruct('ProductVersion', '$($V.VERSION)')])]),
    VarFileInfo([VarStruct('Translation', [0x412, 1200])])
  ]
)
"@, [Text.UTF8Encoding]::new($false))

Write-Host '== freeze engine'
$env:PYTHONHASHSEED = '0'
$piArgs = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN', '--onedir', '--console',
          '--name', 'MaimusiEngine', '--icon', "$Root\build\windows\gen\Maimusi.ico",
          '--version-file', "$Work\version_info.txt",
          '--paths', "$Root\engine", '--distpath', "$Work\dist", '--workpath', "$Work\work", '--specpath', $Work,
          '--add-data', "$Root\engine\hangul_ime\converter_data;hangul_ime\converter_data",
          '--add-data', "$Root\engine\hangul_ime\spacing_data;hangul_ime\spacing_data")
if ($Refiner) { $piArgs += @('--add-data', "$Refiner;hangul_ime\models") }
$piArgs += @('--collect-data', 'kiwipiepy_model', '--collect-data', 'pint',
           '--hidden-import', 'kiwipiepy_model', '--hidden-import', 'korean_lunar_calendar',
           '--hidden-import', 'hangul_ime.pipe_service',
           '--exclude-module', 'tkinter', '--exclude-module', 'pytest', '--exclude-module', 'PySide6',
           '--exclude-module', 'IPython', '--exclude-module', 'matplotlib', '--exclude-module', 'pint.testsuite',
           "$Root\engine\hangul_engine_main.py")
& $Python @piArgs
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

Write-Host '== engine smoke test'
$exe = "$Work\dist\MaimusiEngine\MaimusiEngine.exe"
$psi = [Diagnostics.ProcessStartInfo]::new($exe)
$psi.UseShellExecute = $false; $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true
$psi.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
# Process.Start writes the preamble of [Console]::InputEncoding to the redirected
# stdin: a UTF-8 BOM under code page 65001, which the engine rejects as JSON.
$consoleIn = $null
try { $consoleIn = [Console]::InputEncoding; [Console]::InputEncoding = [Text.UTF8Encoding]::new($false) } catch { }
try {
    $proc = [Diagnostics.Process]::Start($psi)
} finally {
    if ($consoleIn) { try { [Console]::InputEncoding = $consoleIn } catch { } }
}
$in = [IO.StreamWriter]::new($proc.StandardInput.BaseStream, [Text.UTF8Encoding]::new($false))
$in.WriteLine('{"id":1,"op":"space","text":"아버지가방에들어가신다"}'); $in.Close()
$reply = $proc.StandardOutput.ReadToEnd()
$proc.WaitForExit()
Write-Host "   $(($reply -split "`n" | Where-Object { $_ })[-1])"
if ($reply -notmatch '아버지가 방에 들어가신다') { throw 'engine smoke test failed' }

Write-Host '== third-party licences'
New-Item -ItemType Directory -Force "$Work\licenses" | Out-Null
& $Python "$Root\tools\collect_licenses.py" "$Work\licenses"
if ($LASTEXITCODE) { throw 'licence collection failed' }
Copy-Item "$Root\engine\hangul_ime\spacing_data\LICENSE-open-korean-text.txt" "$Work\licenses"
[IO.File]::WriteAllText("$Work\dist\version.txt", "$($V.ENGINE_VERSION)+$($V.VERSION_BUILD)")
