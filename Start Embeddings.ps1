$ErrorActionPreference='Stop'
try {
    $body=@{model='text-embedding-nomic-embed-text-v1.5';input='search_query: health check'} | ConvertTo-Json
    Invoke-RestMethod http://127.0.0.1:1234/v1/embeddings -Method Post -ContentType application/json -Body $body -TimeoutSec 5 | Out-Null
    Write-Host 'Nomic embeddings online'; return
} catch {}
$lms=Join-Path $env:USERPROFILE '.lmstudio/bin/lms.exe'
& $lms server start --port 1234
& $lms load text-embedding-nomic-embed-text-v1.5 --identifier text-embedding-nomic-embed-text-v1.5 --gpu off
if ($LASTEXITCODE -ne 0) { throw 'The local Nomic embedding model could not be started.' }
