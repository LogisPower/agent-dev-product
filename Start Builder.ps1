$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Start Embeddings.ps1')
& (Join-Path (Split-Path $PSScriptRoot) 'Bonsai/Start Bonsai 9B Vision.ps1')
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:8090/api/health' -TimeoutSec 2 | Out-Null
    Write-Host 'Builder is already running: http://127.0.0.1:8090'
    return
} catch {}
& (Join-Path (Split-Path $PSScriptRoot) 'Bonsai/Start Bonsai 27B.ps1')
$pythonPath = 'C:/Users/LOGIS_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$previousLocation = Get-Location
try {
    Set-Location -LiteralPath $PSScriptRoot
    & $pythonPath -c 'import server; print("Logis dependency check passed")'
    if ($LASTEXITCODE -ne 0) { throw 'Logis dependency check failed. The error above identifies the missing component.' }
} finally { Set-Location -LiteralPath $previousLocation.Path }
$builderProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-u', ('"' + (Join-Path $PSScriptRoot 'server.py') + '"')) `
    -WorkingDirectory $PSScriptRoot `
    -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'server.out.log') `
    -RedirectStandardError (Join-Path $PSScriptRoot 'server.err.log')
$builderProcess.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'server.pid')
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        Invoke-RestMethod 'http://127.0.0.1:8090/api/health' -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {
        $builderProcess.Refresh()
        if ($builderProcess.HasExited) {
            Get-Content -LiteralPath (Join-Path $PSScriptRoot 'server.err.log') -Tail 25
            throw 'Logis exited during startup. See the error above.'
        }
        Start-Sleep -Milliseconds 500
    }
}
if (-not $ready) { throw 'Logis did not become ready. Check server.err.log.' }
Write-Host 'Logis is ready: http://127.0.0.1:8090'

& (Join-Path $PSScriptRoot 'Start Paperclip.ps1')
