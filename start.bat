@echo off
chcp 65001 >nul
cd /d "%~dp0"
title EC start

echo ==========================================
echo  1/4  MySQL
echo ==========================================
docker compose up -d --wait
if errorlevel 1 goto docker_err

echo.
echo ==========================================
echo  2/4  mock-gateway  http://localhost:8010
echo ==========================================
rem  the dummy payment API runs in its own process (design 10.2.4).
rem  when it lived inside the backend, POST /orders called itself over HTTP
rem  and timed out about 2.3 percent of the time (found in R-23).
if not exist "backend\.venv\Scripts\python.exe" goto venv_err
start "EC mock-gateway :8010" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn mock_app:app --port 8010"

echo.
echo ==========================================
echo  3/4  backend  http://localhost:8000
echo ==========================================
start "EC backend :8000" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn main:app --port 8000 --reload"

echo.
echo ==========================================
echo  4/4  frontend  http://localhost:3000
echo ==========================================
if not exist "frontend\node_modules" goto node_err
start "EC frontend :3000" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo waiting for the frontend to come up ...
timeout /t 12 >nul
start "" http://localhost:3000/products

echo.
echo ------------------------------------------
echo  opened http://localhost:3000/products
echo.
echo  three black windows are now running.
echo  closing them stops the app.
echo  stop.bat also stops MySQL.
echo ------------------------------------------
timeout /t 6 >nul
exit /b 0

:docker_err
echo.
echo [NG] docker compose failed.
echo      Is Docker Desktop running? Start it and try again.
pause
exit /b 1

:venv_err
echo.
echo [NG] backend\.venv not found.
echo      run:  python -m venv backend\.venv
echo            backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
pause
exit /b 1

:node_err
echo.
echo [NG] frontend\node_modules not found.
echo      run:  npm --prefix frontend install
pause
exit /b 1
