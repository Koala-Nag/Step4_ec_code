@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo stopping MySQL ...
docker compose down
echo.
echo MySQL stopped. Data is kept.
echo Close the two black windows to stop backend / frontend.
echo.
pause
