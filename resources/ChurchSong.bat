@echo off
setlocal
echo Starting ChurchSong ...
ChurchSong.exe %*
if errorlevel 1 pause
