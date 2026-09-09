<#
Start or stop the four services locally without Docker.
Usage:  pwsh scripts/devstack.ps1 start|stop|restart
#>
param([Parameter(Mandatory = $true)][ValidateSet('start', 'stop', 'restart')][string]$Action)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'

$services = @(
    @{ Name = 'gateway';           Port = 8000 },
    @{ Name = 'agent1_gatekeeper'; Port = 8001 },
    @{ Name = 'agent2_researcher'; Port = 8002 },
    @{ Name = 'agent3_coach';      Port = 8003 }
)

function Stop-Stack {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*uvicorn*services.*' }
    foreach ($p in $procs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { }
    }
    Start-Sleep -Seconds 2
    Write-Host "stopped $(($procs | Measure-Object).Count) process(es)"
}

function Start-Stack {
    if (-not (Test-Path $logs)) { New-Item -ItemType Directory -Path $logs | Out-Null }
    foreach ($s in $services) {
        $out = Join-Path $logs "$($s.Name).log"
        Start-Process -FilePath $python -WindowStyle Hidden -WorkingDirectory $root `
            -ArgumentList @('-m', 'uvicorn', "services.$($s.Name).main:app",
                            '--host', '127.0.0.1', '--port', $s.Port) `
            -RedirectStandardOutput $out -RedirectStandardError "$out.err"
        Write-Host "started $($s.Name) on $($s.Port)"
    }
    Start-Sleep -Seconds 12
    foreach ($s in $services) {
        try {
            $r = Invoke-RestMethod "http://127.0.0.1:$($s.Port)/health" -TimeoutSec 5
            Write-Host "  $($s.Name): $($r.service) db=$($r.database)"
        } catch {
            Write-Host "  $($s.Name): UNHEALTHY - $_"
        }
    }
}

switch ($Action) {
    'stop'    { Stop-Stack }
    'start'   { Start-Stack }
    'restart' { Stop-Stack; Start-Stack }
}
