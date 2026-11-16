@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Web-Demo.ps1"
if errorlevel 1 pause
