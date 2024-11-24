@echo off
setlocal
<nul set /p=Starting ChurchSong ... >&2
if exist %~dp0bin\uv.exe (
    set UV=%~dp0bin\uv.exe
) else (
    for %%X in (uv.exe) do set UV=%%~$PATH:X
)
if not defined UV (
    echo error: uv.exe can be found neither in subfolder 'bin' nor in PATH
    exit /b 1
)
%UV% run %~dpn0.py %*
if errorlevel 1 pause
