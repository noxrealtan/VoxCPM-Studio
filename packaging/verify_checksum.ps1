# ============================================================================
#  Verificateur d integrite SHA-256 - embarque dans chaque release GitHub.
#  Verifie que le VoxCPMStudio.exe telecharge est exactement le binaire publie
#  par GitHub Actions (empreinte reprise du fichier checksums.txt de la release).
#  Usage (double-clic : passez par verifier.bat) :
#    .\verify_checksum.ps1                          # verifie VoxCPMStudio.exe
#    .\verify_checksum.ps1 -Path chemin\du\fichier  # verifie un autre fichier
#    .\verify_checksum.ps1 -ChecksumFile autre.txt  # autre liste d empreintes
#  Code retour : 0 si l empreinte correspond, 1 sinon (scriptable).
# ============================================================================
param(
  [string]$Path,
  [string]$ChecksumFile
)
$ErrorActionPreference = "Stop"

# Fichier a verifier : VoxCPMStudio.exe a cote du script, sinon celui passe en parametre.
if (-not $Path) {
  $Path = Join-Path $PSScriptRoot "VoxCPMStudio.exe"
}
if (-not (Test-Path -LiteralPath $Path)) {
  Write-Host "[X] Fichier introuvable : $Path"
  Write-Host "    Placez verify_checksum.ps1 dans le dossier du .exe telecharge,"
  Write-Host "    ou relancez : .\verify_checksum.ps1 -Path chemin\du\fichier"
  exit 1
}

# Liste d empreintes : checksums.txt a cote du script.
if (-not $ChecksumFile) {
  $ChecksumFile = Join-Path $PSScriptRoot "checksums.txt"
}
if (-not (Test-Path -LiteralPath $ChecksumFile)) {
  Write-Host "[X] Liste d empreintes introuvable : $ChecksumFile"
  Write-Host "    Telechargez checksums.txt depuis la page de la release GitHub."
  exit 1
}

$expected = $null
foreach ($line in Get-Content -LiteralPath $ChecksumFile) {
  $t = $line.Trim()
  if (-not $t -or $t.StartsWith("#")) { continue }
  $parts = $t -split "\s+", 2
  if ($parts.Count -eq 2 -and [IO.Path]::GetFileName($parts[1]) -eq [IO.Path]::GetFileName($Path)) {
    $expected = $parts[0].ToLower()
    break
  }
}
if (-not $expected) {
  Write-Host "[X] Aucune empreinte pour $([IO.Path]::GetFileName($Path)) dans $([IO.Path]::GetFileName($ChecksumFile))"
  exit 1
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLower()
Write-Host ("Fichier    : {0}" -f $Path)
Write-Host ("SHA-256    : {0}" -f $hash)
if ($hash -eq $expected) {
  Write-Host "[OK] Empreinte verifiee : ce fichier est bien celui publie par GitHub Actions."
  exit 0
}
Write-Host "[X] EMPREINTE DIFFERENTE (attendue : $expected)"
Write-Host "    Ne faites pas confiance a ce fichier : re-telechargez-le depuis la release officielle."
exit 1
