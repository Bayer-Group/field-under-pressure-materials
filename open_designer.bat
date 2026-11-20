@echo off
setlocal
echo ========================================================
echo   Uruchamianie Qt Designera z kontrolkami QGIS
echo ========================================================

set DESIGNER_BAT=C:\Program Files\QGIS 3.44.6\bin\qgis-designer.bat
set UI_FILE=%~dp0qgis_plugin\pyqgis_fastapi_bridge\gui\dockwidget.ui

if exist "%DESIGNER_BAT%" (
    echo Uruchamianie: "%DESIGNER_BAT%" "%UI_FILE%"
    start "" "%DESIGNER_BAT%" "%UI_FILE%"
) else (
    echo [BLAD] Nie znaleziono qgis-designer.bat w domyslnej sciezce.
    pause
)
