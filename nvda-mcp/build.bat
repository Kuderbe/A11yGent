@echo off
REM Package the add-on directory into an NVDA add-on zip.
REM Output: nvdaMcp-<version>.nvda-addon (in the current directory).
REM
REM The .nvda-addon file is simply a ZIP whose root contains manifest.ini
REM and the plugin package directories.

setlocal ENABLEDELAYEDEXPANSION
set ROOT=%~dp0
set SRC=%ROOT%addon

if not exist "%SRC%\manifest.ini" (
	echo ERROR: %SRC%\manifest.ini not found.
	exit /b 1
)

REM Read the add-on version from the packaged manifest so the output
REM filename always matches manifest.ini (single source of truth). The
REM manifest line looks like:  version = "0.2.0"
set VERSION=
for /f "tokens=2 delims==" %%V in ('findstr /b /c:"version" "%SRC%\manifest.ini"') do (
	set RAW=%%V
)
REM Strip surrounding spaces and double quotes from the captured value.
set RAW=%RAW: =%
set VERSION=%RAW:"=%
if "%VERSION%"=="" (
	echo ERROR: could not read version from %SRC%\manifest.ini.
	exit /b 1
)

set OUT=%ROOT%nvdaMcp-%VERSION%.nvda-addon

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