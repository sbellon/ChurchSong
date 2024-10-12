@REM @py -3 -m pip install -r %~dp0requirements.txt
@py -3 %~dpn0.py %*
@if errorlevel 1 pause
