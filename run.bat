@echo off
cd /d "%~dp0"

echo ============================================================
echo  [1/2] Generating dashboard.html
echo ============================================================
python agent\main.py

echo.
echo ============================================================
echo  [2/2] Generating dashboard_top30.html
echo ============================================================
python agent\main_top30.py

echo.
echo ============================================================
echo  Done. Check dashboard.html and dashboard_top30.html
echo ============================================================
pause
