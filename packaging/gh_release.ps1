# ============================================================================
#  Publie une release GitHub et y attache un asset - REST pur (Invoke-RestMethod),
#  sans installer le CLI gh sur le runner. Utilise par .github/workflows/release.yml
#  Exemple :
#    .\gh_release.ps1 -Tag v0.1.0 -Asset dist\VoxCPMStudio.exe `
#      -Repo OWNER/REPO -Token $env:GITHUB_TOKEN
# ============================================================================
param(
  [Parameter(Mandatory=$true)][string]$Tag,
  [Parameter(Mandatory=$true)][string]$Asset,
  [Parameter(Mandatory=$true)][string]$Repo,
  [Parameter(Mandatory=$true)][string]$Token
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $Asset)) { throw "Asset manquant : $Asset" }
$bytes = [System.IO.File]::ReadAllBytes($Asset)
$name  = [System.IO.Path]::GetFileName($Asset)
$assetSize = "{0:N1} MB" -f ($bytes.Length / 1MB)
Write-Host "Asset : $name ($assetSize)"

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
  $body = @{
    tag_name = $Tag
    name     = "VoxCPM Studio $Tag"
    body     = "Application Windows autonome (VoxCPMStudio.exe), construite et " +
               "smoke-testee par GitHub Actions au tag $Tag."
    draft    = $false
    prerelease = $false
  } | ConvertTo-Json
  $release = Invoke-RestMethod -Headers $headers -Method Post `
    -Uri "https://api.github.com/repos/$Repo/releases" `
    -ContentType "application/json" -Body $body
  Write-Host "Release creee : $($release.html_url)"
} else {
  Write-Host "Release existante : $($release.html_url)"
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
