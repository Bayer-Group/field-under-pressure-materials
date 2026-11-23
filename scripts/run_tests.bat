@echo off
setlocal enabledelayedexpansion
echo ========================================================
echo   Uruchamianie testow jednostkowych (PyQGIS Bridge)
echo ========================================================

:: Wykrywanie dzialajacego interpretera Pythona
set PYTHON_EXE=

:: 1. Sprawdz czy w PATH dziala realny python (pomijajac puste aliasy Windows Store)
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 set PYTHON_EXE=python

if "!PYTHON_EXE!"=="" (
    py --version >nul 2>&1
    if %ERRORLEVEL% EQU 0 set PYTHON_EXE=py
)

if "!PYTHON_EXE!"=="" (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
        set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    ) else if exist "%PROGRAMFILES%\QGIS 3.44.6\apps\Python312\python.exe" (
        set "PYTHON_EXE=%PROGRAMFILES%\QGIS 3.44.6\apps\Python312\python.exe"
    )
)

if "!PYTHON_EXE!"=="" (
    echo [BLAD] Nie znaleziono interpretera Pythona w PATH ani w standardowych sciezkach.
    echo Zainstaluj Pythona lub uruchom testy w srodowisku wirtualnym.
    pause
    exit /b 1
)

:: Run from the repository root (this script lives in scripts/)
cd /d "%~dp0.."

echo Uzywany interpreter: "!PYTHON_EXE!"
echo.

"!PYTHON_EXE!" -m unittest discover -s tests -p "test_*.py" -v

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUKCES] Wszystkie testy przeszly pomyslnie!
) else (
    echo.
    echo [BLAD] Czesc testow zakonczyla sie niepowodzeniem.
)

if "%~1"=="" pause

