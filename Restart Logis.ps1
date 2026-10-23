$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'server.pid'
if (Test-Path -LiteralPath $pidFile) {
    $builderPid = [int](Get-Content -LiteralPath $pidFile)
    $builderProcess = Get-Process -Id $builderPid -ErrorAction SilentlyContinue
    if ($builderProcess) {
        $expectedPython = 'C:\Users\LOGIS_USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if ($builderProcess.Path -ne $expectedPython) { throw 'Unexpected backend process.' }
        $projects = Invoke-RestMethod 'http://127.0.0.1:8090/api/projects' -TimeoutSec 3
        if ($projects | Where-Object { $_.running }) { throw 'Stop the running chat in Logis before restarting.' }
        Stop-Process -Id $builderPid -Force -Confirm:$false
        Wait-Process -Id $builderPid -ErrorAction SilentlyContinue
    }
}
& (Join-Path $PSScriptRoot 'Start Builder.ps1')
Start-Process 'http://127.0.0.1:8090/'
