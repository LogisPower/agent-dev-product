@echo off
"C:\Users\LOGIS_USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe" -NoLogo -NoProfile -File "%~dp0Connect Docker.ps1"
if errorlevel 1 pause
