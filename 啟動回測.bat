@echo off
echo ========================================
echo   期貨策略回測平台 V2
echo ========================================
echo.

cd /d "%~dp0"
streamlit run app.py

pause
