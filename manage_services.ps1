param(
  [ValidateSet("start", "stop", "restart", "status")]
  [string]$Action = "restart"
)

$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Stop-ListeningPort([int]$Port) {
  $pids = Get-NetTCPConnection -LocalPort $Port -State Listen | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($pid in $pids) {
    Stop-Process -Id $pid -Force
  }
}

function Stop-KnowClawProcesses {
  $backendProcs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -match "knowclaw_v2_mvp_refactor" -and $_.CommandLine -match "uvicorn app.main:app"
  }
  foreach ($proc in $backendProcs) {
    Stop-Process -Id $proc.ProcessId -Force
  }

  $frontendProcs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "node.exe" -and $_.CommandLine -match "knowclaw_v2_mvp_refactor" -and ($_.CommandLine -match "vite" -or $_.CommandLine -match "npm run dev")
  }
  foreach ($proc in $frontendProcs) {
    Stop-Process -Id $proc.ProcessId -Force
  }
}

function Wait-Port([int]$Port, [int]$TimeoutSec = 25) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen | Select-Object -First 1
    if ($listener) {
      return $true
    }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Show-Status {
  $backend = Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique
  $frontend5173 = Get-NetTCPConnection -LocalPort 5173 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique
  $frontend5181 = Get-NetTCPConnection -LocalPort 5181 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique

  Write-Host "Backend (8000):" ($backend -join ", ")
  Write-Host "Frontend (5173):" ($frontend5173 -join ", ")
  Write-Host "Frontend (5181):" ($frontend5181 -join ", ")
}

if ($Action -eq "stop" -or $Action -eq "restart") {
  Write-Host "Stopping existing KnowClaw services..."
  Stop-KnowClawProcesses
  # Fallback: force-kill python/node to avoid zombie duplicates on Windows
  Get-Process -Name python,node -ErrorAction SilentlyContinue | Stop-Process -Force
  Stop-ListeningPort -Port 8000
  Stop-ListeningPort -Port 5173
  Stop-ListeningPort -Port 5181
  Start-Sleep -Seconds 1
}

if ($Action -eq "start" -or $Action -eq "restart") {
  Write-Host "Starting backend on :8000"
  Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning >> backend_service.log 2>&1" -WorkingDirectory "$root\backend"

  Write-Host "Starting frontend on :5173"
  Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort" -WorkingDirectory "$root\frontend"

  $backendOk = Wait-Port -Port 8000
  $frontendOk = Wait-Port -Port 5173

  if (-not $backendOk) {
    Write-Host "Backend failed to start on :8000"
  }
  if (-not $frontendOk) {
    Write-Host "Frontend failed to start on :5173"
  }
}

Show-Status
