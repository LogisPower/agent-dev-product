$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force runtime/docker-config | Out-Null
docker --config "$PSScriptRoot/runtime/docker-config" info
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with the Linux engine first. No host-shell fallback is enabled.' }
docker --config "$PSScriptRoot/runtime/docker-config" build -t local-builder-runtime:1 runtime
if ($LASTEXITCODE -ne 0) { throw 'Sandbox image build failed.' }
