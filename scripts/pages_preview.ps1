param([switch]$Stop, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$distPath = Join-Path $projectRoot 'web\dist-pages'
$runtimePath = Join-Path $projectRoot '.runtime'
$pidPath = Join-Path $runtimePath 'pages-preview.pid'
$baseUrl = 'http://127.0.0.1:8010'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = 'python' }

if ($Stop) {
    if (-not (Test-Path -LiteralPath $pidPath)) { Write-Host 'No recorded Pages preview process.'; exit 0 }
    $previewProcessId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $previewProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $previewProcessId"
    if ($previewProcess) {
        if (-not $previewProcess.CommandLine -or $previewProcess.CommandLine.IndexOf($distPath, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw 'Recorded PID belongs to another process; it was not stopped.'
        }
        Stop-Process -Id $previewProcessId -ErrorAction Stop
    }
    Remove-Item -LiteralPath $pidPath
    Write-Host 'Pages preview stopped.'
    exit 0
}

function Test-PagesReady {
    try { return ((Invoke-RestMethod "$baseUrl/data/snapshot.json" -TimeoutSec 2).schema_version -eq 1) }
    catch { return $false }
}
if (-not (Test-Path -LiteralPath (Join-Path $distPath 'index.html'))) { throw 'Run prepare_pages.ps1 first.' }
if (-not (Test-PagesReady)) {
    if (Get-NetTCPConnection -State Listen -LocalPort 8010 -ErrorAction SilentlyContinue) { throw 'Port 8010 is in use by another service.' }
    New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
    $options = @{
        FilePath = $pythonPath
        ArgumentList = @('-m', 'http.server', '8010', '--bind', '127.0.0.1', '--directory', ('"{0}"' -f $distPath))
        WorkingDirectory = $projectRoot
        WindowStyle = 'Hidden'
        RedirectStandardOutput = Join-Path $runtimePath 'pages-preview-out.log'
        RedirectStandardError = Join-Path $runtimePath 'pages-preview-error.log'
        PassThru = $true
    }
    $startedProcess = Start-Process @options
    $startedProcess.Id | Set-Content -LiteralPath $pidPath
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-PagesReady) { $ready = $true; break }
        $startedProcess.Refresh()
        if ($startedProcess.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) {
        $startedProcess.Refresh()
        if (-not $startedProcess.HasExited) { $startedProcess.Kill() }
        Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
        throw 'Pages preview failed to start; check .runtime/pages-preview-error.log.'
    }
}
Write-Host "$baseUrl/#/"
if (-not $NoBrowser) { Start-Process "$baseUrl/#/" }
