@echo off
REM Package the add-on directory into an NVDA add-on zip.
REM Output: nvdaMcp-<version>.nvda-addon (in the current directory).
REM
REM The .nvda-addon file is simply a ZIP whose root contains manifest.ini
REM and the plugin package directories.

setlocal ENABLEDELAYEDEXPANSION
set ROOT=%~dp0
set SRC=%ROOT%addon
set OUT=%ROOT%nvdaMcp-0.1.0.nvda-addon

if not exist "%SRC%\manifest.ini" (
	echo ERROR: %SRC%\manifest.ini not found.
	exit /b 1
)

if exist "%OUT%" del "%OUT%"

echo Building %OUT% from %SRC%

REM Prefer PowerShell's Compress-Archive since it ships with every modern Windows.
powershell -NoProfile -Command ^
	"Compress-Archive -Path '%SRC%\*' -DestinationPath '%OUT%.zip' -Force"
if errorlevel 1 (
	echo Compress-Archive failed.
	exit /b 1
)
move /Y "%OUT%.zip" "%OUT%" >nul

echo Built %OUT%
endlocal