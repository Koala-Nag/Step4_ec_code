@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo loading seed 01-06 ...
for %%f in (01_prefecture 02_master 03_demo 04_product 05_product_image 06_demo_stock) do (
  if exist "db\seed\%%f.sql" (
    echo   %%f.sql
    docker compose exec -T db mysql -uroot -plocalonly ec_koala < db\seed\%%f.sql
  )
)
echo.
echo done.
pause
