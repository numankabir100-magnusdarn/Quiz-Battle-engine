@echo off
setlocal EnableExtensions
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo [ERROR] Run this script as Administrator.
  exit /b 1
)
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
netsh advfirewall firewall delete rule name="EEE Brain Battle TCP %PORT%" >nul 2>&1
netsh advfirewall firewall add rule name="EEE Brain Battle TCP %PORT%" dir=in action=allow protocol=TCP localport=%PORT% profile=any >nul

netsh advfirewall firewall delete rule name="EEE Brain Battle ESP32 UDP 4210" >nul 2>&1
netsh advfirewall firewall add rule name="EEE Brain Battle ESP32 UDP 4210" dir=in action=allow protocol=UDP localport=4210 profile=any >nul

if exist "%PYTHON%" (
  netsh advfirewall firewall delete rule name="EEE Brain Battle Python314" >nul 2>&1
  netsh advfirewall firewall add rule name="EEE Brain Battle Python314" dir=in action=allow program="%PYTHON%" enable=yes profile=any >nul
)
echo Firewall rules configured for TCP port %PORT% and UDP port 4210.
endlocal
