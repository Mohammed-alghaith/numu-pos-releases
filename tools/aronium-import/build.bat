@echo off
REM Builds a single-file Windows .exe from aronium_to_grocerypos.py.
REM Run this once on a Windows machine that has Python 3.9+ installed.
REM Output: dist\aronium-to-grocerypos.exe (portable, no Python install needed on target).

setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python is not on PATH. Install Python 3 from https://www.python.org/downloads/ first.
    exit /b 1
)

echo Installing PyInstaller...
python -m pip install --upgrade pyinstaller || exit /b 1

echo Building executable...
python -m PyInstaller --onefile --console --name aronium-to-grocerypos aronium_to_grocerypos.py || exit /b 1

echo.
echo Done. The executable is at: %cd%\dist\aronium-to-grocerypos.exe
echo Usage: aronium-to-grocerypos.exe path\to\aronium-export.csv
