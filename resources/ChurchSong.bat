@echo off
setlocal
<nul set /p=Starting ChurchSong ... >&2
ChurchSong.exe %*
if errorlevel 1 pause
