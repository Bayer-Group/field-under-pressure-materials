@echo off
setlocal
echo ========================================================
echo   Podlinkowanie wtyczki QGIS (PyQGIS FastAPI Bridge)
echo ========================================================

set TARGET_DIR=%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\pyqgis_fastapi_bridge
set SOURCE_DIR=%~dp0..\qgis_plugin\pyqgis_fastapi_bridge

if not exist "%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins" (
    mkdir "%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins"
)

if exist "%TARGET_DIR%" (
    echo Usuwanie starego powiazania...
    rmdir "%TARGET_DIR%"
)

echo Tworzenie lacza symbolicznego (junction):
echo   Zrodlo: %SOURCE_DIR%
echo   Cel:    %TARGET_DIR%

mklink /J "%TARGET_DIR%" "%SOURCE_DIR%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUKCES] Wtyczka PyQGIS FastAPI Bridge zostala podlinkowana!
    echo Otworz QGIS i wlacz wtyczke w: Wtyczki -> Zarzadzaj wtyczkami.
) else (
    echo.
    echo [BLAD] Nie udalo sie utworzyc powiazania.
)

if "%~1"=="" pause

