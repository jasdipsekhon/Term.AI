@echo off
cd /d "%~dp0"
set "DIR=%~dp0"
set "DIR=%DIR:~0,-1%"
echo Setting up Term.AI...

python -m venv .venv
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Configuring Claude Desktop...

.venv\Scripts\python.exe configure.py "%DIR%"
if errorlevel 1 (
    echo ERROR: Could not update Claude Desktop config. Edit it manually -- see README.
    pause
    exit /b 1
)

echo.
echo Done! Restart Claude Desktop to load Term.AI.
echo.
pause
