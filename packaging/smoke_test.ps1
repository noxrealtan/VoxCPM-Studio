# ============================================================================
#  Smoke test du .exe gelé (utilisé par .github/workflows/windows.yml).
#  Environnement CI : ni poids de modèle, ni voxcpm2-cli, ni PyTorch.
#  Le test n'affirme donc que ce qui y est vrai :
#    1. le serveur embarqué démarre et répond /api/health ok:true
#    2. l'interface est servie sur /
#    3. une demande de modèle natif est rejetée 400 avec le message clair
#    4. gguf.available est false dans cet environnement (ni binaire ni poids)
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
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while (-not $uriBase) {
    if ($proc.HasExited) {
      throw ("Le .exe s'est arrete (code {0}). Sortie : {1}" -f $proc.ExitCode,
        (Get-Content smoke_out.log, smoke_err.log -ErrorAction SilentlyContinue -Raw -Join ""))
    }
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
      $owner = Get-NetTCPConnection -State Listen -OwningProcess $proc.Id `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    } else {
      $owner = (netstat -ano | Select-String "LISTENING") | ForEach-Object {
        $parts = $_.ToString() -split "\s+"
        if ($parts[-1] -eq "$($proc.Id)" -and $parts[2] -match "^127\.0\.0\.1:(\d+)$") {
          [PSCustomObject]@{ LocalAddress = $parts[2] }
        }
      } | Select-Object -First 1
    }
    if ($owner) {
      $port = ($owner.LocalAddress -split ":")[-1]
      $uriBase = "http://127.0.0.1:$port"
    } elseif ((Get-Date) -gt $deadline) {
      throw ("Aucun port ecoute par le .exe (PID {0}) apres {1}s. Sortie : {2}" -f $proc.Id, $TimeoutSec,
        (Get-Content smoke_out.log, smoke_err.log -ErrorAction SilentlyContinue -Raw -Join ""))
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

  Write-Host "Smoke test OK : health=$($health.ok), UI servie, natif->400 clair, gguf indisponible."
} finally {
  if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  Remove-Item Env:VOXCPM_BROWSER -ErrorAction SilentlyContinue
  Get-ChildItem smoke_out.log, smoke_err.log -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host "--- $($_.Name) ---"; Get-Content $_.FullName -Raw }
}
