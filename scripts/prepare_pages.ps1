$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$webPath = Join-Path $projectRoot 'web'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = 'python' }
Push-Location -LiteralPath $webPath
try {
    if (-not (Test-Path -LiteralPath 'node_modules')) {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    }
    & npm.cmd run export:pages
    if ($LASTEXITCODE -ne 0) { throw 'Snapshot export failed.' }
    & npm.cmd run build:pages
    if ($LASTEXITCODE -ne 0) { throw 'Static build failed.' }
} finally { Pop-Location }
& $pythonPath (Join-Path $PSScriptRoot 'package_pages.py')
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
Write-Host 'Ready: web\dist-pages (website), dist\github-pages-site.zip (upload package).'
Write-Host 'GitHub Actions source repository: dist\github-pages-source.zip'
