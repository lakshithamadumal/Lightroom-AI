@echo off
setlocal enabledelayedexpansion

echo ======================================================================
echo   Lightroom AI Studio Edition 2.0 - Standalone Windows Packager
echo ======================================================================
echo.

echo [1/5] Cleaning previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist\Lightroom_AI_Studio_v2.0.0_Windows" rmdir /s /q "dist\Lightroom_AI_Studio_v2.0.0_Windows"
if exist "dist\Lightroom_AI_Studio_v2.0.0_Windows.zip" del /q "dist\Lightroom_AI_Studio_v2.0.0_Windows.zip"

echo [2/5] Compiling standalone executable with PyInstaller...
python -m PyInstaller --noconfirm LightroomAI.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller compilation failed!
    exit /b 1
)

echo [3/5] Copying release documentation and templates...
set "TARGET_DIR=dist\Lightroom_AI_Studio_v2.0.0_Windows"
if exist ".env.example" copy /y ".env.example" "%TARGET_DIR%\.env.example" >nul
if exist "README.md" copy /y "README.md" "%TARGET_DIR%\README.md" >nul
if exist "LICENSE" copy /y "LICENSE" "%TARGET_DIR%\LICENSE" >nul

echo [4/5] Creating release ZIP archive...
powershell -NoProfile -Command "Compress-Archive -Path '%TARGET_DIR%' -DestinationPath 'dist\Lightroom_AI_Studio_v2.0.0_Windows.zip' -Force"
if errorlevel 1 (
    echo [WARNING] Failed to generate ZIP archive.
)

echo [5/5] Build Complete!
echo.
echo ======================================================================
echo   Distribution generated successfully:
echo   Folder: dist\Lightroom_AI_Studio_v2.0.0_Windows\
echo   Executable: dist\Lightroom_AI_Studio_v2.0.0_Windows\LightroomAI.exe
echo   Zip Package: dist\Lightroom_AI_Studio_v2.0.0_Windows.zip
echo ======================================================================
echo.
exit /b 0
