$ErrorActionPreference='Stop'
try { Invoke-RestMethod http://127.0.0.1:3100/api/health -TimeoutSec 2 | Out-Null; Write-Host 'Paperclip is online'; return } catch {}
$env:PAPERCLIP_TELEMETRY_DISABLED='1'
$env:DO_NOT_TRACK='1'
$env:PATH='C:/Users/LOGIS_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin;'+$env:PATH
$node='C:/Users/LOGIS_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$cli=Join-Path $PSScriptRoot 'paperclip/node_modules/paperclipai/dist/index.js'
$data=Join-Path $PSScriptRoot 'Data/paperclip'
$p=Start-Process -FilePath $node -ArgumentList @(('"'+$cli+'"'),'run','--data-dir',('"'+$data+'"')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'paperclip.out.log') -RedirectStandardError (Join-Path $PSScriptRoot 'paperclip.err.log')
$p.Id | Set-Content (Join-Path $PSScriptRoot 'paperclip.pid')
Write-Host 'Starting Paperclip at http://127.0.0.1:3100'
