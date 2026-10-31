param([switch]$SkipChecks)
$ErrorActionPreference = 'Stop'
$builderRoot = Split-Path $PSScriptRoot
$python = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Codex Python runtime was not found.' }
$previousLocation = Get-Location
try {
    Set-Location -LiteralPath $PSScriptRoot
    & $python -c "import sys; sys.path.insert(0,'deps'); import fastapi.testclient, psycopg, uvicorn; print('Candidate dependencies accessible')"
    if ($LASTEXITCODE -ne 0) { throw 'Candidate dependencies are inaccessible. Run this script under the Windows account that installed Logis.' }
    $existing = $null
    try { $existing = Invoke-RestMethod 'http://127.0.0.1:8092/health' -TimeoutSec 2 } catch {}
    if ($existing) {
        if ($existing.service -ne 'logis-candidate') { throw 'Port 8092 belongs to a different service.' }
        Write-Host 'Candidate is already running. This launcher does not stop existing processes.'
        return
    }
    $folder = Get-ChildItem -LiteralPath $PSScriptRoot -Directory -Filter 'postgres-restore-*' | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $folder) { throw 'No isolated restore cluster exists. No new database will be created.' }
    $cluster = [IO.Path]::GetFullPath($folder.FullName)
    $expectedParent = [IO.Path]::GetFullPath($PSScriptRoot)
    if ((Split-Path $cluster) -ne $expectedParent -or -not $folder.Name.StartsWith('postgres-restore-')) { throw 'Unexpected cluster path.' }
    $pgctl = Join-Path $builderRoot 'paperclip/node_modules/@embedded-postgres/windows-x64/native/bin/pg_ctl.exe'
    if (-not (Test-Path -LiteralPath $pgctl)) { throw 'Embedded PostgreSQL executable is missing.' }
    & $pgctl -D $cluster status | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
        $listener.Start()
        $candidatePort = $listener.LocalEndpoint.Port
        $listener.Stop()
        & $pgctl -D $cluster -l (Join-Path $cluster 'candidate-start.log') -o "-h 127.0.0.1 -p $candidatePort" -w -t 30 start
        if ($LASTEXITCODE -ne 0) { throw 'Isolated PostgreSQL startup failed. Existing data and processes were left intact.' }
    }
    if (-not $SkipChecks) {
        foreach ($test in @('test_model_response.py','test_candidate_api.py','test_memory_replacement.py','test_personal_memory.py','test_conversation_understanding.py')) {
            & $python $test
            if ($LASTEXITCODE -ne 0) { throw "Candidate check failed: $test" }
        }
    }
    $modelReady = $false
    try { $modelReady = (Invoke-RestMethod 'http://127.0.0.1:8081/health' -TimeoutSec 2).status -eq 'ok' } catch {}
    if (-not $modelReady) {
        & (Join-Path (Split-Path $builderRoot) 'Bonsai/Start Bonsai 27B.ps1')
        if (-not $?) { throw 'Model startup failed.' }
    }
    $process = Start-Process -FilePath $python -ArgumentList @('-u', ('"' + (Join-Path $PSScriptRoot 'serve_candidate.py') + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'candidate.out.log') -RedirectStandardError (Join-Path $PSScriptRoot 'candidate.err.log')
    $process.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'candidate.pid')
    $ready = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        try { $ready = (Invoke-RestMethod 'http://127.0.0.1:8092/health' -TimeoutSec 2).service -eq 'logis-candidate' } catch {}
        if ($ready) { break }
        $process.Refresh()
        if ($process.HasExited) { throw 'Candidate exited. See rework/candidate.err.log.' }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Candidate did not become ready. See rework/candidate.err.log.' }
    Write-Host 'Candidate ready: http://127.0.0.1:8092/preview'
    Write-Host 'Bonsai may still be loading. Failed understanding jobs can be retried from message history once it is ready.'
    Start-Process 'http://127.0.0.1:8092/preview'
} finally { Set-Location -LiteralPath $previousLocation.Path }
