@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0_tools\start_dashboards.ps1"
if errorlevel 1 pause
