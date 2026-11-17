# Installer artwork: the side panel of the welcome/finish pages (WizardImageFile)
# and the header tile of the inner pages (WizardSmallImageFile), at every size
# Inno Setup picks from by display scale. Usage: make_wizard.ps1 <out dir>
# Prints the two comma-separated file lists for the .iss defines.
param([Parameter(Mandatory)][string]$Out, [string]$Tagline = '한글 자동 띄어쓰기 입력기', [string]$Publisher = '세반시옷',
      [string]$Name = '매무시')
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\mark.ps1"
New-Item -ItemType Directory -Force $Out | Out-Null

function Get-Family([string[]]$names) {
    $installed = (New-Object System.Drawing.Text.InstalledFontCollection).Families | ForEach-Object Name
    foreach ($n in $names) { if ($installed -contains $n) { return [System.Drawing.FontFamily]::new($n) } }
    [System.Drawing.FontFamily]::new('Malgun Gothic')
}
# Wordmark in a Myeongjo (as on macOS), text in the UI sans.
$serif = Get-Family @('Noto Serif KR SemiBold', 'Noto Serif KR', 'KoPubWorldBatang Medium', 'Batang')
$sans = Get-Family @('Noto Sans KR', 'Noto Sans CJK KR', 'Malgun Gothic')

function Save-Bmp($bmp, $path) {
    # Inno Setup takes 24-bit BMPs for these images.
    $flat = [System.Drawing.Bitmap]::new($bmp.Width, $bmp.Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $g = [System.Drawing.Graphics]::FromImage($flat); $g.DrawImage($bmp, 0, 0, $bmp.Width, $bmp.Height); $g.Dispose()
    $flat.Save($path, [System.Drawing.Imaging.ImageFormat]::Bmp); $flat.Dispose()
}

function Draw-Centered($g, [string]$text, $family, [float]$size, $style, $color, [float]$cx, [float]$cy, [float]$tracking = 0) {
    $font = [System.Drawing.Font]::new($family, $size, $style, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = [System.Drawing.SolidBrush]::new($color)
    $fmt = [System.Drawing.StringFormat]::GenericTypographic
    if ($tracking -eq 0) {
        $sz = $g.MeasureString($text, $font, 10000, $fmt)
        $g.DrawString($text, $font, $brush, $cx - $sz.Width / 2, $cy - $sz.Height / 2, $fmt)
    } else {
        # Letter-spaced: draw character by character.
        $widths = foreach ($ch in $text.ToCharArray()) { $g.MeasureString([string]$ch, $font, 10000, $fmt).Width }
        $total = ($widths | Measure-Object -Sum).Sum + $tracking * ($text.Length - 1)
        $x = $cx - $total / 2
        $h = $g.MeasureString($text, $font, 10000, $fmt).Height
        for ($i = 0; $i -lt $text.Length; $i++) {
            $g.DrawString([string]$text[$i], $font, $brush, $x, $cy - $h / 2, $fmt); $x += $widths[$i] + $tracking
        }
    }
    $font.Dispose(); $brush.Dispose()
}

function New-Canvas([int]$w, [int]$h) {
    $bmp = [System.Drawing.Bitmap]::new($w, $h, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'; $g.TextRenderingHint = 'AntiAliasGridFit'; $g.InterpolationMode = 'HighQualityBicubic'
    @($bmp, $g)
}

# Side panel: 옻칠 ground, the mark in 청자, the name in 한지.
$panels = @(@(164, 314), @(192, 386), @(246, 459), @(273, 556), @(328, 604), @(355, 700), @(410, 797))
$large = foreach ($p in $panels) {
    $w = $p[0]; $h = $p[1]; $k = $w / 164.0
    $bmp, $g = New-Canvas $w $h
    $grad = [System.Drawing.Drawing2D.LinearGradientBrush]::new([System.Drawing.Point]::new(0, 0), [System.Drawing.Point]::new(0, $h),
        [System.Drawing.Color]::FromArgb(0x16, 0x1A, 0x19), [System.Drawing.Color]::FromArgb(0x0E, 0x10, 0x0F))
    $g.FillRectangle($grad, 0, 0, $w, $h)
    # A large faint mark bleeding off the lower right corner.
    $faint = [System.Drawing.Color]::FromArgb(16, $Celadon)
    Draw-Mark $g ($w * 0.78) ($h * 0.86) ($w * 1.35) $true ([System.Drawing.Color]::FromArgb(0x10, 0x12, 0x11)) $faint $faint
    $top = $h * 0.25
    Draw-Mark $g ($w / 2) $top ($w * 0.50)
    Draw-Centered $g $Name $serif (30 * $k) ([System.Drawing.FontStyle]::Regular) $Hanji ($w / 2) ($top + 62 * $k) (3 * $k)
    Draw-Centered $g $Tagline $sans (9.5 * $k) ([System.Drawing.FontStyle]::Regular) ([System.Drawing.Color]::FromArgb(170, $Hanji)) ($w / 2) ($top + 92 * $k)
    # A thin rule and the publisher at the foot.
    $pen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(60, $Celadon), [float][math]::Max(1, $k))
    $g.DrawLine($pen, $w / 2 - 14 * $k, $h - 40 * $k, $w / 2 + 14 * $k, $h - 40 * $k)
    Draw-Centered $g $Publisher $sans (8.5 * $k) ([System.Drawing.FontStyle]::Regular) ([System.Drawing.Color]::FromArgb(130, $Hanji)) ($w / 2) ($h - 26 * $k) (1.5 * $k)
    $g.Dispose()
    $path = Join-Path $Out "wizard-$w.bmp"; Save-Bmp $bmp $path; $bmp.Dispose(); $path
}

# Header tile of the inner pages (white header in the modern style).
$tiles = @(@(55, 55), @(64, 68), @(83, 80), @(92, 97), @(110, 106), @(119, 123), @(138, 140))
$small = foreach ($p in $tiles) {
    $w = $p[0]; $h = $p[1]
    $bmp, $g = New-Canvas $w $h
    $g.Clear([System.Drawing.Color]::White)
    $side = [math]::Min($w, $h) * 0.86
    $x = ($w - $side) / 2; $y = ($h - $side) / 2
    $g.FillPath([System.Drawing.SolidBrush]::new($Lacquer), (Get-TilePath $x $y $side))
    Draw-Mark $g ($w / 2) ($h / 2) ($side * 0.9) ($side -lt 48)
    $g.Dispose()
    $path = Join-Path $Out "wizard-small-$w.bmp"; Save-Bmp $bmp $path; $bmp.Dispose(); $path
}
($large -join ',')
($small -join ',')
