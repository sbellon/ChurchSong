@REM @py -3 -m pip install python-pptx requests
@py -3 %~dpn0.py %*
@if errorlevel 1 pause
