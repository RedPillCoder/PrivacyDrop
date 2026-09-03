@echo off
rem =========================================================================
rem PrivacyDrop — release build (Windows)
rem
rem Runs the test suite, builds the exe, creates the portable zip and
rem source zip, generates SHA-256 checksums, and (if makensis is installed)
rem produces the NSIS installer.
rem
rem Output:  release\<version>\
rem =========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

rem ---- read version ------------------------------------------------------
for /f "usebackq tokens=*" %%v in (VERSION) do set "VER=%%v"
set "VER=%VER: =%"
if "%VER%"=="" (echo !!  Cannot read VERSION & exit /b 1)
echo Building PrivacyDrop v%VER%

rem ---- virtual env -------------------------------------------------------
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

if not exist ".venv" (
    echo [1/6] Creating virtual environment...
    %PY% -m venv .venv || goto :err
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul

rem ---- dependencies ------------------------------------------------------
echo [2/6] Installing dependencies...
pip install -q -r requirements-dev.txt || goto :err

rem ---- tests -------------------------------------------------------------
echo [3/6] Running test suite...
set FAIL=0
for %%t in (test_engine test_full test_security test_privacy test_app_features) do (
    python -m tests.%%t >nul 2>&1
    if !errorlevel! neq 0 (
        echo   !!  tests\%%t.py failed
        set FAIL=1
    ) else (
        echo   [ok]  %%t.py
    )
)
if %FAIL% neq 0 (
    echo !!  Tests failed — aborting release build
    exit /b 1
)

rem ---- exe ---------------------------------------------------------------
echo [4/6] Building PrivacyDrop.exe...
pip install -q pyinstaller >nul
pyinstaller PrivacyDrop.spec --noconfirm --clean --distpath dist || goto :err
if not exist "dist\PrivacyDrop.exe" (echo !!  exe not produced & exit /b 1)
for /F "usebackq" %%F in (`powershell -NoProfile -Command "(Get-Item 'dist\PrivacyDrop.exe').Length / 1MB"`) do echo   dist\PrivacyDrop.exe  (%%F MB^)

rem ---- zips --------------------------------------------------------------
echo [5/6] Packaging release zips...
set "REL=release\%VER%"
if exist "%REL%" rmdir /s /q "%REL%"
mkdir "%REL%" 2>nul

:: portable zip
mkdir "%TEMP%\pd-portable" 2>nul
copy "dist\PrivacyDrop.exe"   "%TEMP%\pd-portable\" >nul
copy "LICENSE"                "%TEMP%\pd-portable\" >nul
copy "README.md"              "%TEMP%\pd-portable\" >nul
copy "CHANGELOG.md"           "%TEMP%\pd-portable\" >nul
powershell -NoProfile -Command ^
    "Compress-Archive -Path '%TEMP%\pd-portable\*' -DestinationPath '%REL%\PrivacyDrop-%VER%-portable.zip' -Force -CompressionLevel Optimal"
rmdir /s /q "%TEMP%\pd-portable" 2>nul
echo   [ok]  portable zip

:: source zip
powershell -NoProfile -Command ^
    "Get-ChildItem -Recurse -File | Where-Object { $_.FullName -notmatch '(release|\.venv|__pycache__|dist|\.git|\.pyc|tests\\tmp)' } | ForEach-Object { $_.FullName } | Compress-Archive -DestinationPath '%REL%\PrivacyDrop-%VER%-source.zip' -Force -CompressionLevel Optimal"
echo   [ok]  source zip

rem ---- installer ---------------------------------------------------------
echo [6/6] Building installer...
where makensis >nul 2>nul
if %errorlevel%==0 (
    makensis installer.nsi
    if exist "dist\PrivacyDrop-%VER%-Setup.exe" (
        copy "dist\PrivacyDrop-%VER%-Setup.exe" "%REL\" >nul
        echo   [ok]  installer
    ) else (
        echo   [warn]  makensis ran but installer not produced
    )
) else (
    echo   [info]  makensis not found — installer.nsi ready to build when NSIS is installed
)

rem ---- checksums ---------------------------------------------------------
echo.
echo Generating SHA-256 checksums...
powershell -NoProfile -Command ^
    "Get-ChildItem '%REL%\*' -File | ForEach-Object { $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash; '{0}  {1}' -f $h.ToLower(), $_.Name } | Tee-Object 'release\SHA256SUMS'"

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║  PrivacyDrop v%VER% — release ready                      ║
echo ║  Artifacts:  release\%VER%\                              ║
echo ╚══════════════════════════════════════════════════════════╝
exit /b 0

:err
echo.
echo !!  Build failed.  See messages above.
exit /b 1
