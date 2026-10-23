$ErrorActionPreference = 'Stop'
$dockerExe = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$configPath = Join-Path $PSScriptRoot 'runtime/docker-config'
$reportPath = Join-Path $PSScriptRoot 'runtime/docker-connection-report.json'
New-Item -ItemType Directory -Force -Path $configPath | Out-Null
$report = [ordered]@{ time = (Get-Date).ToString('o'); identity = (& whoami); status = 'checking'; attempts = @() }
try {
    if (-not (Test-Path -LiteralPath $dockerExe)) { throw 'Docker Desktop is not installed at its expected location.' }
    $endpoint = $null
    foreach ($candidate in @('npipe:////./pipe/dockerDesktopLinuxEngine', 'npipe:////./pipe/docker_engine')) {
        $probe = & $dockerExe --config $configPath --host $candidate info --format '{{.OSType}}|{{.ServerVersion}}' 2>&1
        $probeExit = $LASTEXITCODE
        $report.attempts += @{ endpoint = $candidate; exit_code = $probeExit; output = ($probe -join "`n") }
        if ($probeExit -eq 0 -and ($probe -join '') -match 'linux\|') { $endpoint = $candidate; break }
    }
    if (-not $endpoint) { throw 'Cannot access a Linux Docker engine. Confirm Docker Desktop says Engine running. If this says Access denied from your normal Windows account, review Docker Desktop permissions; this script does not change account groups or pipe permissions.' }
    Write-Host 'Docker access verified. Preparing the isolated Logis runtime...'
    & $dockerExe --config $configPath --host $endpoint build -t local-builder-runtime:1 (Join-Path $PSScriptRoot 'runtime')
    if ($LASTEXITCODE -ne 0) { throw 'The runtime image build failed. Check the download/build error above.' }
    $testDir = Join-Path $PSScriptRoot ('runtime/docker-check-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $testDir | Out-Null
    & $dockerExe --config $configPath --host $endpoint run --rm --read-only --cap-drop=ALL --security-opt=no-new-privileges --pids-limit=128 --memory=1g --cpus=2 --user=1000:1000 --network=none --tmpfs /tmp:rw,nosuid,size=64m --mount "type=bind,source=$testDir,target=/workspace" --workdir /workspace local-builder-runtime:1 sh -lc 'printf LOGIS-DOCKER-VERIFIED > proof.txt; node --version; python3 --version'
    if ($LASTEXITCODE -ne 0 -or (Get-Content -LiteralPath (Join-Path $testDir 'proof.txt') -Raw) -ne 'LOGIS-DOCKER-VERIFIED') { throw 'Container execution or project-folder writes failed.' }
    @{ endpoint = $endpoint; verified = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime/docker-connection.json') -Encoding utf8
    $report.status = 'verified'
    $report.docker_verified = $true
    $report.endpoint = $endpoint
    $report.proof = $testDir
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Host 'Docker isolation and file writes passed. Restarting Logis...'
    & (Join-Path $PSScriptRoot 'Restart Logis.ps1')
} catch {
    $report.status = $(if ($report.docker_verified) { 'docker_verified_app_restart_failed' } else { 'failed' })
    $report.error = $_.Exception.Message
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Host $report.error -ForegroundColor Red
    Write-Host "Diagnostic report: $reportPath"
    exit 1
}
