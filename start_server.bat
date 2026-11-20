@echo off
setlocal EnableExtensions
title EEE Brain Battle Server
echo ============================================
echo   EEE Brain Battle - Phase 1 Game Server
echo   EEECi FA'26  Module 06
echo ============================================
echo.

cd /d "%~dp0"

set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON%" (
    echo [ERROR] Required interpreter not found:
    echo         %PYTHON%
    pause
    exit /b 1
)

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

echo [*] Starting server on 0.0.0.0:%PORT% ...
echo [*] Local hub: http://localhost:%PORT%/hub
echo [*] Local display: http://localhost:%PORT%/display
echo [*] Phone URLs - open one of these on the same Wi-Fi (http, not https):
"%PYTHON%" -c "import sys,socket; p=sys.argv[1]; print(chr(10).join('    http://'+ip+':'+p+'/hub' for ip in sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if not item[4][0].startswith(('127.','169.254.'))})))" "%PORT%"
echo [*] Press Ctrl+C to stop.
echo.

"%PYTHON%" -m uvicorn server.main:app --host 0.0.0.0 --port %PORT%
pause
exit /b %ERRORLEVEL%
