# Draws the Maimusi icon (macos/tools/make_icons.swift: 옻칠 바탕에 청자색 옷깃,
# 흰 동정, 띄어쓰기 부호) at the Windows icon sizes and packs them into an .ico
# with PNG entries. Usage: make_icon.ps1 <out.ico>
param([Parameter(Mandatory)][string]$Out)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

. "$PSScriptRoot\mark.ps1"

function Draw([int]$size) {
    $bmp = [System.Drawing.Bitmap]::new($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.Clear([System.Drawing.Color]::Transparent)
    # Rounded square tile, 1/16 margin; the mark fills 92% of it.
    $m = $size / 16.0; $w = $size - 2*$m
    $g.FillPath([System.Drawing.SolidBrush]::new($Lacquer), (Get-TilePath $m $m $w))
    Draw-Mark $g ($size/2) ($size/2) ($w * 0.92) ($size -lt 32)
    $g.Dispose()
    $ms = [System.IO.MemoryStream]::new()
    if ($size -ge 256) {
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    } else {
        # Small sizes as a classic 32-bit DIB (bottom-up BGRA + AND mask): every
        # icon reader accepts it, unlike PNG entries below 256 px.
        $bw = [System.IO.BinaryWriter]::new($ms)
        $maskRow = [int]([math]::Ceiling($size / 32.0) * 4)
        $bw.Write([uint32]40); $bw.Write([int32]$size); $bw.Write([int32]($size * 2))
        $bw.Write([uint16]1); $bw.Write([uint16]32); $bw.Write([uint32]0)
        $bw.Write([uint32]($size * $size * 4 + $maskRow * $size)); $bw.Write([int32]0); $bw.Write([int32]0)
        $bw.Write([uint32]0); $bw.Write([uint32]0)
        for ($y = $size - 1; $y -ge 0; $y--) {
            for ($x = 0; $x -lt $size; $x++) {
                $c = $bmp.GetPixel($x, $y)
                $bw.Write([byte]$c.B); $bw.Write([byte]$c.G); $bw.Write([byte]$c.R); $bw.Write([byte]$c.A)
            }
        }
        $bw.Write([byte[]]::new($maskRow * $size))
        $bw.Flush()
    }
    $bmp.Dispose()
    , $ms.ToArray()
}

$sizes = 16, 20, 24, 32, 40, 48, 64, 256
$images = foreach ($s in $sizes) { , (Draw $s) }
$fs = [System.IO.File]::Create($Out)
$bw = [System.IO.BinaryWriter]::new($fs)
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]; $len = $images[$i].Length
    $bw.Write([byte]($s % 256)); $bw.Write([byte]($s % 256)); $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([uint16]1); $bw.Write([uint16]32); $bw.Write([uint32]$len); $bw.Write([uint32]$offset)
    $offset += $len
}
foreach ($img in $images) { $bw.Write([byte[]]$img) }
$bw.Close()
