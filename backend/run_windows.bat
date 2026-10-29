@echo off
REM ============================================================
REM  NEXORA backend chalao (Windows)
REM  Band karne ke liye: Ctrl + C
REM ============================================================
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [X] Pehle setup_windows.bat chalao (ek hi baar).
  pause
  exit /b 1
)
echo NEXORA backend chalu ho raha hai...
echo Band karne ke liye: Ctrl + C
echo.
".venv\Scripts\python.exe" run.py
pause
