# ============================================================================
#  Publie une release GitHub et y attache un asset - REST pur (Invoke-RestMethod),
#  sans installer le CLI gh sur le runner. Utilise par .github/workflows/release.yml
#  Les notes sont enrichies automatiquement : taille et SHA-256 du binaire tel
#  que publie, plus le changelog passe via -NotesFile (genere par le workflow).
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
  "Application Windows autonome (VoxCPMStudio.exe), construite et smoke-testee par GitHub Actions au tag $Tag.",
  "",
  "## Telechargement",
  "- **VoxCPMStudio.exe** - $sizeMb MB ($($bytes.Length) octets)",
  "- **SHA-256** : $sha"
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

# Un seul upload par release : si un asset du meme nom existe, on le remplace.
foreach ($a in @($release.assets)) {
  if ($a.name -eq $name) {
    Write-Host "Asset deja present, suppression avant remplacement..."
    Invoke-RestMethod -Headers $headers -Method Delete `
      -Uri "https://api.github.com/repos/$Repo/releases/assets/$($a.id)" | Out-Null
  }
}

$upload = Invoke-RestMethod -Method Post `
  -Uri "https://uploads.github.com/repos/$Repo/releases/$($release.id)/assets?name=$name" `
  -Headers @{ Authorization = "Bearer $Token"; Accept = "application/vnd.github+json" } `
  -ContentType "application/octet-stream" -Body $bytes

Write-Host "Asset publie : $($upload.browser_download_url)"
