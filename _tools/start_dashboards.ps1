$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = (Get-Command python -ErrorAction Stop).Source
$port = 5180
$scriptPath = Join-Path $PSScriptRoot 'pcb_dashboard\server.py'
try {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in @($listener)) {
        if (-not $connection) { continue }
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $connection.OwningProcess)
        if ([string]$process.CommandLine -notlike "*$scriptPath*") {
            throw "Port $port is used by another program. Close it, then run this again."
        }
        Stop-Process -Id $connection.OwningProcess -Force
        Start-Sleep -Milliseconds 500
    }
    $log = Join-Path $env:TEMP "bms-designs-dashboard-$port"
    Start-Process -FilePath $pythonPath -ArgumentList ('"{0}"' -f $scriptPath) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput "$log.out.log" -RedirectStandardError "$log.err.log"
    $ready = $false
    for ($i = 0; $i -lt 20 -and -not $ready; $i++) {
        $client = New-Object System.Net.Sockets.TcpClient
        try { $ready = $client.ConnectAsync('127.0.0.1', $port).Wait(500) -and $client.Connected } catch {} finally { $client.Dispose() }
        if (-not $ready) { Start-Sleep -Milliseconds 300 }
    }
    if (-not $ready) { throw "Dashboard did not start. See $log.err.log" }
    Start-Process "http://localhost:$port/"
    Write-Host "Board Boxes: http://localhost:$port/"
} catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
