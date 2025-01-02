@echo off
setlocal
<nul set /p=Starting ChurchSong ... >&2
ChurchSong %*
if errorlevel 1 pause
