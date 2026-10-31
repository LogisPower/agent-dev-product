@echo off
powershell.exe -NoLogo -NoProfile -File "%~dp0Start candidate.ps1"
if errorlevel 1 pause
