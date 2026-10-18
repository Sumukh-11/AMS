@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install Python 3.11 or newer and try again.
    pause
    exit /b 1
)

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Desktop build tools are missing.
    echo Run: python -m pip install -r requirements-desktop.txt
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --clean stride_desktop.spec
if errorlevel 1 (
    echo The Stride desktop build failed. Review the PyInstaller output above.
    pause
    exit /b 1
)

powershell -NoProfile -Command "Compress-Archive -Path 'dist\Stride\*' -DestinationPath 'dist\Stride-Windows.zip' -Force"
if errorlevel 1 (
    echo Stride built successfully, but the portable ZIP could not be created.
    pause
    exit /b 1
)

echo.
echo Desktop app: dist\Stride\Stride.exe
echo Portable package: dist\Stride-Windows.zip
pause