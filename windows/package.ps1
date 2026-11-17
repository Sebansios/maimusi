# Build the Windows installer from build\windows\stage\<version> (windows\build.ps1):
#   build\windows\dist\Maimusi-<version>-Windows.exe (x64 and ARM64) and SHA256SUMS.txt
# The staged files and the installer must pass tools\privacy_scan.py: the only
# identity in them is the publisher (세반시옷), its website and support e-mail.
param([string]$Iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
      # Python with PyInstaller, so the scan also opens the frozen engine's archive.
      [string]$Python = "$PSScriptRoot\..\build\venv-engine\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path "$PSScriptRoot\..").Path
function Read-Env($path) {
    $vars = @{}
    foreach ($line in [IO.File]::ReadAllLines($path, [Text.Encoding]::UTF8)) {
        if ($line -match '^\s*([A-Z_]+)="(.*)"\s*$') { $vars[$Matches[1]] = $Matches[2] }
    }
    $vars
}
& python "$Root\tools\versions.py" check
if ($LASTEXITCODE) { throw 'version check failed' }
$P = Read-Env "$Root\packaging\product.env"
$V = Read-Env "$Root\packaging\version.env"
$Version = $V.VERSION
$Stage = "$Root\build\windows\stage\$Version"
$Dist = "$Root\build\windows\dist"
foreach ($arch in 'x64', 'x86', 'arm64') {
    if (-not (Test-Path "$Stage\$arch\MaimusiTIP.dll")) { throw "not built: $Stage\$arch (run windows\build.ps1)" }
}
if (-not (Test-Path "$Stage\engine\MaimusiEngine.exe")) { Write-Warning 'no CharTec engine in the stage (light engine only)' }
if (-not (Test-Path "$Stage\spacing.hspm")) { Write-Warning 'no light model in the stage (CharTec engine only)' }

Write-Host '== privacy scan (staged files)'
& $Python "$Root\tools\privacy_scan.py" $Stage
if ($LASTEXITCODE) { throw 'privacy scan failed' }

New-Item -ItemType Directory -Force $Dist | Out-Null
$name = "$($P.PRODUCT_FILE)-$Version$($V.RELEASE_FILE_SUFFIX)-Windows"
# Inno Setup reads the licence as UTF-8 only with a byte order mark.
$license = "$Root\build\windows\gen\LICENSE.txt"
$text = [IO.File]::ReadAllText("$Stage\Licenses\LICENSE.txt", [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($license, $text.Replace("`r`n", "`n").Replace("`n", "`r`n"), [Text.UTF8Encoding]::new($true))

Write-Host '== installer artwork'
$art = & powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\tools\make_wizard.ps1" "$Root\build\windows\gen\wizard" `
    -Name $P.PRODUCT_NAME_KO -Tagline $P.TAGLINE_KO -Publisher $P.PUBLISHER_KO
if ($LASTEXITCODE -or $art.Count -lt 2) { throw 'installer artwork failed' }

Write-Host '== installer'
& $Iscc /Q "/DName=$($P.PRODUCT_NAME_KO)" "/DNameEn=$($P.PRODUCT_NAME_EN)" "/DVersion=$Version" "/DBuild=$($V.VERSION_BUILD)" `
    "/DPublisher=$($P.PUBLISHER_KO)" "/DWebsite=$($P.WEBSITE)" "/DEmail=$($P.SUPPORT_EMAIL)" `
    "/DCopyright=Copyright © $($P.COPYRIGHT_YEAR) $($P.PUBLISHER_KO)" "/DStage=$Stage" `
    "/DIcon=$Root\build\windows\gen\Maimusi.ico" "/DLicense=$license" "/DOutDir=$Dist" "/DOutName=$name" `
    "/DWizardImages=$($art[0])" "/DWizardSmall=$($art[1])" `
    "$PSScriptRoot\installer\maimusi.iss"
if ($LASTEXITCODE) { throw 'ISCC failed' }

Write-Host '== privacy scan (installer)'
& $Python "$Root\tools\privacy_scan.py" "$Dist\$name.exe"
if ($LASTEXITCODE) { throw 'privacy scan failed' }

$hash = (Get-FileHash -Algorithm SHA256 "$Dist\$name.exe").Hash.ToLower()
[IO.File]::WriteAllText("$Dist\SHA256SUMS.txt", "$hash  $name.exe`n", [Text.UTF8Encoding]::new($false))
$size = [math]::Round((Get-Item "$Dist\$name.exe").Length / 1MB, 1)
Write-Host "== $Dist\$name.exe ($size MB)"
Write-Host "   sha256 $hash"
