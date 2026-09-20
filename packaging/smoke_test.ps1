# ============================================================================
#  Smoke test du .exe gelé (utilisé par .github/workflows/windows.yml et
#  release.yml). Environnement CI : ni poids de modèle, ni voxcpm2-cli, ni
#  PyTorch. Le test n'affirme que ce qui y est vrai :
#    1. le serveur embarqué démarre et répond /api/health ok:true
#    2. l'interface est servie sur /
#    3. une demande de modèle natif est rejetée 400 avec le message clair
#    4. gguf.available est false dans cet environnement (ni binaire ni poids)
#    5. génération de checksums.txt : SHA-256 de tous les assets de la release
#       (le .exe, le vérificateur embarqué et son lanceur double-clic)
#    6. le manifeste est vérifié par le vérificateur embarqué lui-même
#       (le même code que l'utilisateur exécutera via verifier.bat)
#  Aucune génération audio : impossible sans poids.
#  La fenêtre native (WebView2) n'est PAS testée ici : le .exe démarre en mode
#  VOXCPM_BROWSER=1 (repli navigateur déterministe en CI, sans GUI).
# ============================================================================
param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [int]$TimeoutSec = 60
)
$ErrorActionPreference = "Stop"

$env:VOXCPM_BROWSER = "1"
$proc = Start-Process -FilePath $ExePath -WorkingDirectory (Get-Location) `
  -RedirectStandardOutput smoke_out.log -RedirectStandardError smoke_err.log `
  -PassThru -WindowStyle Hidden
$uriBase = $null
try {
  # --- Découverte du port réellement lié (desktop.py : 8808..8857) ---------
  # PyInstaller onefile : le .exe lancé est un bootloader parent, c'est son
  # processus ENFANT qui possède la socket d'écoute — on matche donc contre
  # l'arbre complet (parent + descendants), pas le seul PID capturé.
  function Get-TreePids([int]$Root) {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Select-Object ProcessId, ParentProcessId
    $tree = New-Object System.Collections.Generic.HashSet[int]
    [void]$tree.Add($Root)
    $changed = $true
    while ($changed) {
      $changed = $false
      foreach ($p in $procs) {
        if ($tree.Contains([int]$p.ParentProcessId) -and -not $tree.Contains([int]$p.ProcessId)) {
          [void]$tree.Add([int]$p.ProcessId); $changed = $true
        }
      }
    }
    ,$tree
  }
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while (-not $uriBase) {
    if ($proc.HasExited) {
      throw ("Le .exe s'est arrete (code {0}). Sortie : {1}" -f $proc.ExitCode,
        (Get-Content smoke_out.log, smoke_err.log -ErrorAction SilentlyContinue | Out-String))
    }
    $tree = Get-TreePids $proc.Id
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
      $owner = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $tree.Contains([int]$_.OwningProcess) } | Select-Object -First 1 |
        ForEach-Object { [PSCustomObject]@{ LocalAddress = "$($_.LocalAddress):$($_.LocalPort)" } }
    } else {
      $owner = (netstat -ano | Select-String "LISTENING") | ForEach-Object {
        $parts = $_.ToString() -split "\s+"
        if ($tree.Contains([int]$parts[-1]) -and $parts[2] -match "^127\.0\.0\.1:(\d+)$") {
          [PSCustomObject]@{ LocalAddress = $parts[2] }
        }
      } | Select-Object -First 1
    }
    if ($owner) {
      $port = ($owner.LocalAddress -split ":")[-1]
      $uriBase = "http://127.0.0.1:$port"
    } elseif ((Get-Date) -gt $deadline) {
      throw ("Aucun port ecoute par le .exe (PID {0}) apres {1}s. Sortie : {2}" -f $proc.Id, $TimeoutSec,
        (Get-Content smoke_out.log, smoke_err.log -ErrorAction SilentlyContinue | Out-String))
    } else {
      Start-Sleep -Milliseconds 500
    }
  }
  Write-Host "Port découvert : $uriBase"

  # --- 1. /api/health doit répondre ok:true --------------------------------
  $deadline = (Get-Date).AddSeconds(20)
  $health = $null
  do {
    try {
      $health = Invoke-RestMethod -Uri "$uriBase/api/health" -TimeoutSec 3
      break
    } catch {
      if ((Get-Date) -gt $deadline) { throw "/api/health injoignable sur $uriBase : $_" }
      Start-Sleep -Milliseconds 800
    }
  } while ($true)
  if (-not $health.ok) { throw "health.ok est false : $($health | ConvertTo-Json -Compress)" }

  # --- 2. L'interface est servie sur / -------------------------------------
  $ui = Invoke-WebRequest -Uri "$uriBase/" -TimeoutSec 10
  $ct = $ui.Headers["Content-Type"]
  if ($ui.Content -notmatch "VoxCPM" -or $ct -notmatch "text/html") {
    throw "L'interface n'est pas servie correctement (Content-Type: $ct)"
  }

  # --- 3. Modèle natif sans PyTorch -> 400 avec message clair --------------
  $code = $null; $body = $null
  try {
    Invoke-WebRequest -Uri "$uriBase/api/generate" -Method Post -TimeoutSec 10 `
      -ContentType "application/json" -Body '{"text":"test CI","model_id":"openbmb/VoxCPM2"}' `
      -ErrorAction Stop | Out-Null
    throw "POST /api/generate natif accepte (200) : le preflight voxcpm n'a pas rejete"
  } catch [Microsoft.PowerShell.Commands.HttpResponseException] {
    $code = [int]$_.Exception.Response.StatusCode
    $body = $_.ErrorDetails.Message
  }
  if ($code -ne 400) { throw "Attendaient 400 pour le modele natif, obtenu $code" }
  if ($body -notmatch "Moteur Python \(voxcpm\) indisponible") {
    throw "Le message 400 ne contient pas la phrase attendue : $body"
  }

  # --- 4. Sans CLI ni poids, gguf.available doit être false ----------------
  if ($health.gguf.available -ne $false) {
    throw "gguf.available devrait être false en CI : $($health.gguf | ConvertTo-Json -Compress)"
  }

  # --- 5. Manifeste des checksums : SHA-256 de tous les assets -------------
  $artifactDir = Split-Path -Parent $ExePath
  $checksumPath = Join-Path $artifactDir "checksums.txt"
  $lines = @("# Verifie avec : verify_checksum.ps1 (verifier.bat) - format sha256sum")
  foreach ($a in @($ExePath, "packaging\verify_checksum.ps1", "packaging\verifier.bat")) {
    if (-not (Test-Path $a)) { throw "Asset de release manquant : $a" }
    $h = (Get-FileHash -Algorithm SHA256 -LiteralPath $a).Hash.ToLower()
    $lines += "$h  $(Split-Path $a -Leaf)"
  }
  $lines | Set-Content -Path $checksumPath -Encoding ascii
  Get-Content $checksumPath

  # --- 6. Le manifeste est vérifié par le vérificateur embarqué ------------
  & powershell -NoProfile -ExecutionPolicy Bypass `
    -File "packaging\verify_checksum.ps1" -Path $ExePath -ChecksumFile $checksumPath
  if ($LASTEXITCODE -ne 0) {
    throw "Le verifier embarque rejette $ExePath (code $LASTEXITCODE)"
  }
  Write-Host "Checksums des 3 assets verifies par verify_checksum.ps1 : OK."

  Write-Host "Smoke test OK : health=$($health.ok), UI servie, natif->400 clair, gguf indisponible, checksums verifies."
} finally {
  if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  Remove-Item Env:VOXCPM_BROWSER -ErrorAction SilentlyContinue
  Get-ChildItem smoke_out.log, smoke_err.log -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host "--- $($_.Name) ---"; Get-Content $_.FullName -Raw }
  # Le manifeste et le vérificateur quittent le job pour la publication
  # (gh_release.ps1 les lit dans SMOKE_ARTIFACTS) — après nettoyage du process.
  $artifactDir = Split-Path -Parent $ExePath
  New-Item -ItemType Directory -Force -Path smoke_artifacts | Out-Null
  foreach ($f in @((Join-Path $artifactDir "checksums.txt"),
                   "packaging\verify_checksum.ps1", "packaging\verifier.bat")) {
    Copy-Item $f smoke_artifacts -Force -ErrorAction SilentlyContinue
  }
  Get-ChildItem smoke_artifacts -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host "artefact pour la release : $($_.Name)" }
}
