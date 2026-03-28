@echo off
title Antigravity Advanced Kit
echo.
echo  ================================================================
echo    ANTIGRAVITY ADVANCED KIT
echo    Protocol: Logic  -^>  Proof  -^>  Harden  -^>  Ship
echo  ================================================================
echo.

:: Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install it from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo [*] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)

:: Activate venv
echo [*] Activating virtual environment...
call venv\Scripts\activate.bat

:: Install dependencies
echo [*] Installing dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

:: Copy .env if it doesn't exist
if not exist ".env" (
    echo [*] Creating .env from template...
    copy .env.example .env >nul
    echo [OK] .env created. Edit it to add your API keys.
    echo.
    echo  ================================================================
    echo    IMPORTANT: Open .env and add your API keys before continuing.
    echo  ================================================================
    echo.
    pause
)

:: Start daemon system in background
echo.
echo [*] Starting daemon system...
start /min "Antigravity Daemon" cmd /c "call venv\Scripts\activate.bat && python daemon.py"
timeout /t 3 /nobreak >nul
echo [OK] Daemon system started (background window).

:: Run onboarding to show context
echo.
echo  ================================================================
echo    SPAWN CONTEXT
echo  ================================================================
echo.
python onboarding.py
echo.

:: Boot the API server
echo  ================================================================
echo    STARTING API SERVER
echo  ================================================================
echo.
echo [*] Server will be at:  http://localhost:8000
echo [*] API docs at:        http://localhost:8000/docs
echo [*] Press Ctrl+C to stop.
echo.
python main.py
