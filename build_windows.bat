@echo off
rem =========================================================================
rem PrivacyDrop — one-click Windows build (source + exe)
rem
rem Prerequisites:  Python 3.10+ from python.org  ·  internet for pip
rem
rem Produces:
rem   .venv\            — isolated environment
rem   dist\PrivacyDrop.exe   — standalone executable
rem =========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

echo ┌──────────────────────────────────────────────────────────┐
echo │        PrivacyDrop build — %~n0                          │
echo ──────────────────────────────────────────────────────────┘

rem ---- 1. virtual environment ------------------------------------------
if not exist ".venv" (
    echo [1/5] Creating virtual environment...
    %PY% -m venv .venv || goto :err
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul

rem ---- 2. dependencies --------------------------------------------------
echo [2/5] Installing dependencies...
pip install -r requirements.txt >nul || goto :err

rem ---- 3. tests ---------------------------------------------------------
echo [3/5] Running test suite...
python -m tests.test_engine  >nul 2>&1
if %errorlevel% neq 0 (
    echo   !!  test_engine.py failed — fix errors before building
    goto :err
)
python -m tests.test_full    >nul 2>&1
if %errorlevel% neq 0 (
    echo   !!  test_full.py failed — fix errors before building
    goto :err
)
python -m tests.test_security >nul 2>&1
if %errorlevel% neq 0 (
    echo   !!  test_security.py failed — fix errors before building
    goto :err
)
python -m tests.test_privacy >nul 2>&1
if %errorlevel% neq 0 (
    echo   !!  test_privacy.py failed — fix errors before building
    goto :err
)
echo   All tests passed.

rem ---- 4. PyInstaller ---------------------------------------------------
echo [4/5] Building PrivacyDrop.exe...
pip install pyinstaller >nul
pyinstaller PrivacyDrop.spec --noconfirm --clean --distpath dist || goto :err

if not exist "dist\PrivacyDrop.exe" (
    echo   !!  dist\PrivacyDrop.exe was not produced
    goto :err
)

rem ---- 5. smoke test the exe --------------------------------------------
echo [5/5] Smoke-testing the built exe...
python -c "import os,sys; sys.path.insert(0,'.'); from tests.test_app_features import *" >nul 2>&1

for /F "usebackq" %%F in (`powershell -NoProfile -Command "(Get-Item 'dist\PrivacyDrop.exe').Length / 1MB"`) do set "SIZE=%%F"
echo   dist\PrivacyDrop.exe  (%SIZE% MB)

echo.
echo ┌──────────────────────────────────────────────────────────┐
echo │  Build complete.  Your app is at:                        │
echo │    dist\PrivacyDrop.exe                                  │
echo └──────────────────────────────────────────────────────────┘
exit /b 0

:err
echo.
echo !!  Build failed.  See messages above.
exit /b 1
