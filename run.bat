@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0dist\Stride\Stride.exe" (
	start "" "%~dp0dist\Stride\Stride.exe"
	exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
	echo Python was not found. Install Python 3.11 or newer and try again.
	pause
	exit /b 1
)

python -m streamlit --version >nul 2>&1
if errorlevel 1 (
	echo Streamlit is not installed for this Python environment.
	echo Run: python -m pip install -r requirements.txt
	pause
	exit /b 1
)

set "PORT=8502"
powershell -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:%PORT%/_stcore/health' -TimeoutSec 2; if ($response.StatusCode -ne 200) { exit 1 } } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
	echo Starting Stride on port %PORT%...
	start "" /B python -m streamlit run app.py --server.port %PORT%
	set /a attempts=0
	goto wait_for_server
)
echo Reusing the Stride server already running on port %PORT%.
goto open_browser

:wait_for_server
powershell -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:%PORT%/_stcore/health' -TimeoutSec 2; if ($response.StatusCode -ne 200) { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto open_browser
set /a attempts+=1
if %attempts% GEQ 30 (
	echo Stride did not become ready. Check the Python and Streamlit installation.
	pause
	exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_for_server

:open_browser
start "" "http://localhost:%PORT%"
echo Stride is ready at http://localhost:%PORT%
pause