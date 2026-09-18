# ============================================================================
#  Convertit le PNG maître en .ico multi-tailles (16/32/48/256) sans dépendance
#  (System.Drawing). Utilisé par packaging\build_exe.bat.
# ============================================================================
param(
  [Parameter(Mandatory=$true)][string]$Source,
  [Parameter(Mandatory=$true)][string]$Output
)
Add-Type -AssemblyName System.Drawing

$dir = Split-Path -Parent $Output
if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

$sizes = @(16, 32, 48, 256)
$src = [System.Drawing.Image]::FromFile($Source)

# Rendu de chaque taille en PNG en mémoire
$pngs = @()
foreach ($s in $sizes) {
  $bmp = New-Object System.Drawing.Bitmap($s, $s)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.DrawImage($src, 0, 0, $s, $s)
  $g.Dispose()
  $pngMs = New-Object System.IO.MemoryStream
  $bmp.Save($pngMs, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  $pngs += ,$pngMs.ToArray()
  $pngMs.Dispose()
}
$src.Dispose()

# Écriture du conteneur ICO (PNG compressés, format Vista+)
$ms = New-Object System.IO.MemoryStream
$bw = New-Object System.IO.BinaryWriter($ms)
$bw.Write([UInt16]0)                     # réservé
$bw.Write([UInt16]1)                     # type : icône
$bw.Write([UInt16]$sizes.Count)          # nombre d'images

$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
  $s = $sizes[$i]
  $w = if ($s -eq 256) { 0 } else { $s } # 256 se code 0
  $bw.Write([Byte]$w)                    # largeur
  $bw.Write([Byte]$w)                    # hauteur
  $bw.Write([Byte]0)                     # palette
  $bw.Write([Byte]0)                     # réservé
  $bw.Write([UInt16]1)                   # plans
  $bw.Write([UInt16]32)                  # bpp
  $bw.Write([UInt32]$pngs[$i].Length)
  $bw.Write([UInt32]$offset)
  $offset += $pngs[$i].Length
}
foreach ($p in $pngs) { $bw.Write($p) }
$bw.Flush()

[System.IO.File]::WriteAllBytes($Output, $ms.ToArray())
$bw.Dispose(); $ms.Dispose()
Write-Host "ICO ecrit : $Output ($(($sizes | ForEach-Object { "$($_)px" }) -join ', '))"
