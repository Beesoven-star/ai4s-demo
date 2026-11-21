param([switch]$Stop, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.runtime'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runnerPath = Join-Path $PSScriptRoot 'preview_server.py'
$pidPath = Join-Path $runtimePath 'preview.pid'
$baseUrl = 'http://127.0.0.1:8000'

if ($Stop) {
    if (-not (Test-Path -LiteralPath $pidPath)) {
        Write-Host 'No recorded preview process.'
        exit 0
    }
    $previewProcessId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $previewProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $previewProcessId"
    if ($previewProcess) {
        if (-not $previewProcess.CommandLine -or $previewProcess.CommandLine.IndexOf($runnerPath, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw 'The recorded PID belongs to another process; it was not stopped.'
        }
        Stop-Process -Id $previewProcessId -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $pidPath) { Remove-Item -LiteralPath $pidPath }
    Write-Host 'AI4S preview stopped.'
    exit 0
}

if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Project Python environment is missing.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'web\dist\index.html'))) {
    throw 'Build the original frontend first: cd web; npm.cmd ci; npm.cmd run build'
}

function Test-PreviewReady {
    try {
        $health = Invoke-RestMethod "$baseUrl/api/health" -TimeoutSec 2
        $schema = Invoke-RestMethod "$baseUrl/openapi.json" -TimeoutSec 2
        return ($health.status -eq 'ok' -and $schema.info.title -eq 'AI4S Daily Archive')
    } catch { return $false }
}

if (-not (Test-PreviewReady)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimePath 'logs') | Out-Null
    $listener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
    if ($listener) { throw 'Port 8000 is already used by another service.' }
    $startOptions = @{
        FilePath = $pythonPath
        ArgumentList = @('-u', ('"{0}"' -f $runnerPath))
        WorkingDirectory = $projectRoot
        WindowStyle = 'Hidden'
        RedirectStandardOutput = (Join-Path $runtimePath 'logs\preview-out.log')
        RedirectStandardError = (Join-Path $runtimePath 'logs\preview-error.log')
        PassThru = $true
    }
    $startedProcess = Start-Process @startOptions
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-PreviewReady) { $ready = $true; break }
        $startedProcess.Refresh()
        if ($startedProcess.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "Preview did not start. See $runtimePath\logs\preview-error.log" }
}

Write-Host "AI4S local workspace is ready: $baseUrl/discover"
Write-Host 'Daily public-source collection runs while the service is on; settings in the web UI. No model calls.'
if (-not $NoBrowser) { Start-Process "$baseUrl/discover" }
