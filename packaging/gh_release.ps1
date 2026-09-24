# ============================================================================
#  Publie une release GitHub et y attache un asset - REST pur (Invoke-RestMethod),
#  sans installer le CLI gh sur le runner. Utilise par .github/workflows/release.yml
#  Les notes sont enrichies automatiquement : taille et SHA-256 du binaire tel
#  que publie, plus le changelog passe via -NotesFile (genere par le workflow).
#  checksums.txt (manifeste des assets, genere ET verifie par le smoke test)
#  est publie en second asset depuis le dossier smoke_artifacts.
#  Exemple :
#    .\gh_release.ps1 -Tag v0.1.0 -Asset dist\VoxCPMStudio.exe `
#      -Repo OWNER/REPO -Token $env:GITHUB_TOKEN -NotesFile release_notes.md
# ============================================================================
param(
  [Parameter(Mandatory=$true)][string]$Tag,
  [Parameter(Mandatory=$true)][string]$Asset,
  [Parameter(Mandatory=$true)][string]$Repo,
  [Parameter(Mandatory=$true)][string]$Token,
  [Parameter(Mandatory=$false)][string]$NotesFile
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $Asset)) { throw "Asset manquant : $Asset" }
$bytes = [System.IO.File]::ReadAllBytes($Asset)
$name  = [System.IO.Path]::GetFileName($Asset)
$sizeMb = "{0:N1}" -f ($bytes.Length / 1MB)
$sha = (Get-FileHash -Algorithm SHA256 -Path $Asset).Hash.ToLower()
Write-Host "Asset : $name ($sizeMb MB, SHA-256 $sha)"

# Changelog genere par le workflow depuis le tag precedent ; absent en
# lancement manuel -> la release est publiee sans section Changements.
$changelog = ""
if ($NotesFile -and (Test-Path -LiteralPath $NotesFile)) {
  $changelog = [System.IO.File]::ReadAllText($NotesFile)
} else {
  Write-Host "Notes absentes ($NotesFile) : release sans changelog."
}

# Corps des notes : empreinte et taille de CE fichier precis, plus le changelog.
$notes = @(
  "![Interface de VoxCPM Studio](https://github.com/$Repo/raw/main/docs/screenshot.png)",
  "",
  "VoxCPM Studio $Tag pour Windows : application autonome, construite et vérifiée par GitHub Actions.",
  "",
  "## À retenir",
  "- Interface claire, plus lisible et adaptée aux écrans de bureau.",
  "- Détection du backend GPU et sonda au démarrage, avec repli CPU automatique.",
  "- Serveur local protégé par validation Host/Origin et jeton de session.",
  "- Bornes de sécurité sur les paramètres de génération et historique rendu sans HTML dynamique.",
  "",
  "## Téléchargement",
  "- **VoxCPMStudio.exe** — $sizeMb Mo ($($bytes.Length) octets)",
  "- **SHA-256 :** $sha",
  "- **Contrôle d’intégrité :** téléchargement joint `checksums.txt`, vérifiable avec `verifier.bat`",
  "- **Vérificateurs :** `verify_checksum.ps1` et `verifier.bat` sont également joints"
)
if ($changelog.Trim()) {
  $notes += ""
  $notes += "## Changements"
  $notes += $changelog.TrimEnd()
}
$body = $notes -join "`n"

$headers = @{
  Authorization = "Bearer $Token"
  Accept        = "application/vnd.github+json"
  "X-GitHub-Api-Version" = "2022-11-28"
}

# La release du tag existe-t-elle deja ?
$release = $null
try {
  $release = Invoke-RestMethod -Headers $headers -Method Get `
    -Uri "https://api.github.com/repos/$Repo/releases/tags/$Tag"
} catch { }  # 404 attendu si premiere publication du tag

if ($null -eq $release) {
  $payload = @{
    tag_name   = $Tag
    name       = "VoxCPM Studio $Tag"
    body       = $body
    draft      = $false
    prerelease = $false
  } | ConvertTo-Json
  $release = Invoke-RestMethod -Headers $headers -Method Post `
    -Uri "https://api.github.com/repos/$Repo/releases" `
    -ContentType "application/json" -Body $payload
  Write-Host "Release creee : $($release.html_url)"
} else {
  # Re-tag : notes rafraichies (empreinte, taille, changelog), jamais perimees.
  Write-Host "Release existante : $($release.html_url) - notes mises a jour."
  $payload = @{ body = $body } | ConvertTo-Json
  Invoke-RestMethod -Headers $headers -Method Patch `
    -Uri "https://api.github.com/repos/$Repo/releases/$($release.id)" `
    -ContentType "application/json" -Body $payload | Out-Null
}

# Assets geres par ce script : remplaces (et non doubles) en cas de re-tag.
$replaced = @($name, "checksums.txt", "verify_checksum.ps1", "verifier.bat")
foreach ($a in @($release.assets)) {
  if ($replaced -contains $a.name) {
    Write-Host "Asset deja present, suppression avant remplacement..."
    Invoke-RestMethod -Headers $headers -Method Delete `
      -Uri "https://api.github.com/repos/$Repo/releases/assets/$($a.id)" | Out-Null
  }
}

function Add-Asset([string]$fname, [byte[]]$data) {
  $u = Invoke-RestMethod -Method Post `
    -Uri "https://uploads.github.com/repos/$Repo/releases/$($release.id)/assets?name=$fname" `
    -Headers @{ Authorization = "Bearer $Token"; Accept = "application/vnd.github+json" } `
    -ContentType "application/octet-stream" -Body $data
  Write-Host "Asset publie : $($u.browser_download_url)"
}

Add-Asset $name $bytes

# checksums.txt en second asset : manifeste genere et verifie par le smoke
# test (empreintes du .exe, du verifier embarque et de son lanceur).
if (Test-Path "smoke_artifacts\checksums.txt") {
  Add-Asset "checksums.txt" ([System.IO.File]::ReadAllBytes("smoke_artifacts\checksums.txt"))
} else {
  throw "smoke_artifacts\checksums.txt manquant : le smoke test a-t-il ete execute ?"
}
foreach ($f in @("smoke_artifacts\verify_checksum.ps1", "smoke_artifacts\verifier.bat")) {
  if (Test-Path $f) {
    Add-Asset (Split-Path $f -Leaf) ([System.IO.File]::ReadAllBytes($f))
  } else {
    Write-Host "Verificateur absent : $f (asset non publie)"
  }
}
