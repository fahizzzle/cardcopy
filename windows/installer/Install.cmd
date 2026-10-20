@echo off
rem Installs CardCopy for this Windows user (copies the CardCopy folder next to this file; no admin rights).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 pause
