@echo off
setlocal
cd /d "%~dp0"

echo === Spar- och Pensionsplan: bygg exe + installationsprogram ===
echo.

set "TEMP_DIST=%TEMP%\SparOchPensionsplan_build\dist"
set "TEMP_WORK=%TEMP%\SparOchPensionsplan_build\build"

echo [1/3] Installerar byggberoenden...
python -m pip install -r requirements-build.txt -q
if errorlevel 1 (
    echo Misslyckades: pip install
    exit /b 1
)

echo.
echo [2/3] Bygger exe med PyInstaller (temp-mapp, undviker OneDrive-las)...
if not exist "%TEMP_DIST%" mkdir "%TEMP_DIST%"
if not exist "%TEMP_WORK%" mkdir "%TEMP_WORK%"
python -m PyInstaller --noconfirm --onedir --windowed --name SparOchPensionsplan --icon pension.ico --distpath "%TEMP_DIST%" --workpath "%TEMP_WORK%" --add-data "Manual.pdf;." --add-data "pension.ico;." --hidden-import plan_save --hidden-import plan_engine --hidden-import paminnelse --hidden-import saldo_pdf --hidden-import utdelning_core --hidden-import utdelning_panel --hidden-import aktiehandel_panel plan2030_app.py
if errorlevel 1 (
    echo Misslyckades: PyInstaller
    exit /b 1
)
if not exist "%TEMP_DIST%\SparOchPensionsplan\SparOchPensionsplan.exe" (
    echo Misslyckades: SparOchPensionsplan.exe hittades inte.
    exit /b 1
)

echo.
echo [3/3] Bygger installationsprogram med Inno Setup...
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup hittades inte. Installera fran https://jrsoftware.org/isinfo.php
    exit /b 1
)

if not exist "installer" mkdir installer
"%ISCC%" /DDistDir="%TEMP_DIST%\SparOchPensionsplan" "%~dp0pensionsplan_setup.iss"
if errorlevel 1 (
    echo Misslyckades: Inno Setup
    exit /b 1
)

echo.
echo === Klart ===
echo Installer: %~dp0installer\SparOchPensionsplan_Setup_1.0.exe
echo.
echo Planer sparas i planer\ bredvid programmet efter installation.
pause
