@echo off
title The Modding Tavern - Launcher Builder
color 0A
echo.
echo  ======================================================
echo   The Modding Tavern - One-Time Builder
echo  ======================================================
echo.
echo  This will create:
echo    TavernLauncher - Server.exe
echo    TavernLauncher - Client.exe
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo  Please install Python from https://python.org
    echo  Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
echo  [OK] Python found.
echo.

:: Read the currently-recorded version out of dependencies\version (a
:: plain text file containing just the version string, e.g. "1.8.3") --
:: shown as the actual current default in the prompt below instead of a
:: hardcoded, eventually-stale example, and used as-is if the person just
:: presses Enter. Whatever they DO end up building with gets written back
:: into this same file, so it stays the source of truth for next time.
set CURRENT_VERSION=
if exist dependencies\version (
    for /f "usebackq delims=" %%v in ("dependencies\version") do set CURRENT_VERSION=%%v
)
if "%CURRENT_VERSION%"=="" set CURRENT_VERSION=0.0.0

set VERSION=
set /p VERSION="Version to build (leave blank to keep %CURRENT_VERSION%): "

if "%VERSION%"=="" set VERSION=%CURRENT_VERSION%
if /i "%VERSION:~0,1%"=="v" set VERSION=%VERSION:~1%

echo.
python dependencies\set_version.py %VERSION% client\version.py server\version.py
if errorlevel 1 (
    echo  [ERROR] Failed to update the version in the source files.
    pause
    exit /b 1
)
echo %VERSION%>dependencies\version

echo.
echo  Installing PyInstaller, Pillow and the console client...
pip install pyinstaller pillow markdown tkinterweb websocket-client -q
if errorlevel 1 (
    echo  [ERROR] Failed to install the build packages.
    pause
    exit /b 1
)

echo.
echo  Building TavernLauncher - Server.exe...
pyinstaller --onefile --windowed --clean --name "TavernLauncher - Server" --icon dependencies\att-unlocked-full.ico --add-data "dependencies\icon_data.py;." --add-data "dependencies\banner_data.py;." --add-data "dependencies\updater.py;." --add-data "tavern_shared\help_content;tavern_shared\help_content" --collect-all tkinterweb --collect-all tkinterweb_tkhtml server\main.py
if errorlevel 1 ( echo [ERROR] Server build failed. & pause & exit /b 1 )

echo.
echo  Building TavernLauncher - Client.exe...
pyinstaller --onefile --windowed --clean --name "TavernLauncher - Client" --icon dependencies\att-unlocked-full.ico --add-data "dependencies\icon_data.py;." --add-data "dependencies\banner_data.py;." --add-data "dependencies\updater.py;." --add-data "tavern_shared\help_content;tavern_shared\help_content" --collect-all tkinterweb --collect-all tkinterweb_tkhtml client\main.py
if errorlevel 1 ( echo [ERROR] Client build failed. & pause & exit /b 1 )

:: Move exes to current folder
if exist "dist\TavernLauncher - Server.exe" move "dist\TavernLauncher - Server.exe" .
if exist "dist\TavernLauncher - Client.exe" move "dist\TavernLauncher - Client.exe" .

:: Cleanup
rmdir /s /q dist >nul 2>&1
rmdir /s /q build >nul 2>&1
del *.spec >nul 2>&1

echo.
echo  ======================================================
echo   Done! Built version %VERSION%. Two files created:
echo     TavernLauncher - Server.exe  -  Run the server
echo     TavernLauncher - Client.exe  -  Join a server
echo  ======================================================
echo.
pause
