$ErrorActionPreference='Stop'
$env:PLAYWRIGHT_BROWSERS_PATH="$PSScriptRoot/runtime/browsers"
& 'C:/Users/LOGIS_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' 'C:/Users/LOGIS_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/cli.js' install chromium
if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed.' }
