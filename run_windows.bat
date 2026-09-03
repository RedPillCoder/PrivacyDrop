@echo off
rem Run PrivacyDrop from source (requires Python 3.8+ from python.org).
setlocal EnableExtensions
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

if not exist ".venv" (
    echo First run: setting up environment...
    %PY% -m venv .venv || goto :err
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip >nul
    python -m pip install -r requirements.txt || goto :err
) else (
    call ".venv\Scripts\activate.bat"
)

start "" pythonw.exe app.py
exit /b 0

:err
echo Setup failed. See messages above.
pause
exit /b 1
