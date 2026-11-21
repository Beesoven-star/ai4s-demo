param([switch]$Stop, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.runtime'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runnerPath = Join-Path $PSScriptRoot 'ic_preview_server.py'
$pidPath = Join-Path $runtimePath 'ic-preview.pid'
$baseUrl = 'http://127.0.0.1:8001'

if ($Stop) {
    if (-not (Test-Path -LiteralPath $pidPath)) { Write-Host 'No recorded IC preview process.'; exit 0 }
    $previewProcessId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $previewProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $previewProcessId"
    if ($previewProcess) {
        if (-not $previewProcess.CommandLine -or $previewProcess.CommandLine.IndexOf($runnerPath, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw 'Recorded PID belongs to another process; it was not stopped.'
        }
        Stop-Process -Id $previewProcessId -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $pidPath) { Remove-Item -LiteralPath $pidPath }
    Write-Host 'IC preview stopped.'
    exit 0
}

function Test-ICReady {
    try {
        $response = Invoke-RestMethod "$baseUrl/ic-exploration-20261110.json" -TimeoutSec 2
        return ($response.schema_version -eq 'ic-exploration-1.0' -and $response.counts.included -eq 163)
    } catch { return $false }
}
if (-not (Test-ICReady)) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'web\dist\ic-exploration-20261110.json'))) {
        throw 'Build the frontend first: npm.cmd run build in web.'
    }
    $listener = Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue
    if ($listener) { throw 'Port 8001 is already in use.' }
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimePath 'logs') | Out-Null
    $startOptions = @{
        FilePath = $pythonPath
        ArgumentList = @('-u', ('"{0}"' -f $runnerPath))
        WorkingDirectory = $projectRoot
        WindowStyle = 'Hidden'
        RedirectStandardOutput = (Join-Path $runtimePath 'logs\ic-preview-out.log')
        RedirectStandardError = (Join-Path $runtimePath 'logs\ic-preview-error.log')
        PassThru = $true
    }
    $startedProcess = Start-Process @startOptions
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-ICReady) { $ready = $true; break }
        $startedProcess.Refresh()
        if ($startedProcess.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw 'IC preview did not start; check .runtime/logs/ic-preview-error.log.' }
}
Write-Host "IC workbench: $baseUrl/"
if (-not $NoBrowser) { Start-Process "$baseUrl/" }
