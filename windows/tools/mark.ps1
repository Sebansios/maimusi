# The 매무시 mark (macos/tools/make_icons.swift, mark_geometry.py): 한복 옷깃(V,
# 오른깃이 왼깃 위로 여며짐)과 그 아래 띄어쓰기 부호(⎵), 120-unit viewBox.
# Dot-source this file; it defines the colors and Draw-Mark.
Add-Type -AssemblyName System.Drawing

$script:Lacquer = [System.Drawing.Color]::FromArgb(0x11, 0x13, 0x12)
$script:Celadon = [System.Drawing.Color]::FromArgb(0x9D, 0xBF, 0xB2)
$script:Hanji = [System.Drawing.Color]::FromArgb(0xE9, 0xE4, 0xD8)

function Get-QuadPoint($a, $c, $b, $t) {
    [System.Drawing.PointF]::new((1-$t)*(1-$t)*$a[0] + 2*(1-$t)*$t*$c[0] + $t*$t*$b[0],
                                 (1-$t)*(1-$t)*$a[1] + 2*(1-$t)*$t*$c[1] + $t*$t*$b[1])
}

# The collar curve moved sideways by d (the 동정 runs parallel to the collar).
function Get-OffsetPath($arm, $d, $t0 = 0, $t1 = 1, $side = 1) {
    $pts = for ($k = 0; $k -le 32; $k++) {
        $t = $t0 + ($t1 - $t0) * $k / 32
        $p = Get-QuadPoint $arm[0] $arm[1] $arm[2] $t
        $vx = 2*(1-$t)*($arm[1][0]-$arm[0][0]) + 2*$t*($arm[2][0]-$arm[1][0])
        $vy = 2*(1-$t)*($arm[1][1]-$arm[0][1]) + 2*$t*($arm[2][1]-$arm[1][1])
        $l = [math]::Sqrt($vx*$vx + $vy*$vy)
        [System.Drawing.PointF]::new($p.X - $vy/$l*$side*$d, $p.Y + $vx/$l*$side*$d)
    }
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $path.AddLines([System.Drawing.PointF[]]$pts)
    $path
}

# Draws the mark centered at (cx, cy), `size` pixels for the 120-unit box.
# $Ground is the color behind it (the gap where the right collar crosses).
function Draw-Mark($g, [float]$cx, [float]$cy, [float]$size, [bool]$Simple = $false,
                   $Ground = $script:Lacquer, $Ink = $script:Celadon, $Trim = $script:Hanji) {
    $state = $g.Save()
    $s = $size / 120.0
    $g.TranslateTransform($cx, $cy); $g.ScaleTransform($s, $s); $g.TranslateTransform(-60, -55)
    $band = if ($Simple) { 9 } else { 7 }
    $leftArm = @(@(36,10), @(44,42), @(60,58))
    $rightArm = @(@(84,10), @(77,44), @(48,67))
    $stroke = {
        param($path, $width, $color)
        $pen = [System.Drawing.Pen]::new($color, $width)
        $pen.StartCap = 'Round'; $pen.EndCap = 'Round'; $pen.LineJoin = 'Round'
        $g.DrawPath($pen, $path)
        $pen.Dispose()
    }
    $g.SetClip([System.Drawing.RectangleF]::new(-40, 20, 200, 200), [System.Drawing.Drawing2D.CombineMode]::Intersect)
    & $stroke (Get-OffsetPath $leftArm 0) $band $Ink
    if (-not $Simple) { & $stroke (Get-OffsetPath $leftArm 7.4 0 0.62 -1) 2.2 $Trim }
    & $stroke (Get-OffsetPath $rightArm 0) ($band + 6) $Ground
    & $stroke (Get-OffsetPath $rightArm 0) $band $Ink
    if (-not $Simple) { & $stroke (Get-OffsetPath $rightArm 7.4 0 0.78 1) 2.2 $Trim }
    $g.Restore($state)
    $state = $g.Save()
    $g.TranslateTransform($cx, $cy); $g.ScaleTransform($s, $s); $g.TranslateTransform(-60, -55)
    $space = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $space.AddBezier(32,81, 32,90, 35,94, 41,94); $space.AddLine(41,94, 79,94); $space.AddBezier(79,94, 85,94, 88,90, 88,81)
    & $stroke $space $band $Ink
    $g.Restore($state)
}

# Rounded-square tile of the app icon.
function Get-TilePath([float]$x, [float]$y, [float]$w) {
    $r = $w * 0.22
    $tile = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $tile.AddArc($x, $y, $r, $r, 180, 90); $tile.AddArc($x+$w-$r, $y, $r, $r, 270, 90)
    $tile.AddArc($x+$w-$r, $y+$w-$r, $r, $r, 0, 90); $tile.AddArc($x, $y+$w-$r, $r, $r, 90, 90)
    $tile.CloseFigure()
    $tile
}
