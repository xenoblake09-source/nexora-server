@echo off
REM ============================================================
REM  NEXORA backend - ek baar ka setup (Windows)
REM  Yeh file:  .venv banati hai, dependencies install karti hai,
REM             .env copy karti hai, aur aapka laptop IP dikhati hai.
REM ============================================================
cd /d "%~dp0"
echo === NEXORA backend setup ===
echo.

where python >nul 2>nul
if errorlevel 1 goto nopython

if exist .venv goto skipvenv
echo [1/3] Virtual environment ban raha hai...
python -m venv .venv
if errorlevel 1 goto fail
goto deps

:skipvenv
echo [1/3] .venv pehle se hai - skip.

:deps
echo [2/3] Dependencies install ho rahi hain (2-3 minit, internet chahiye)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

if exist .env goto doneenv
echo [3/3] .env banaya ja raha hai (.env.example se copy).
copy .env.example .env >nul
goto after

:doneenv
echo [3/3] .env pehle se hai - skip.

:after
echo.
echo ================= AB YEH 2 KAAM KARO =================
echo   1) notepad .env
echo      Option FREE (Gemini):
echo        AI_PROVIDER=gemini
echo        GEMINI_API_KEY=      (aistudio.google.com se free key)
echo      Option OpenAI (paid):
echo        AI_PROVIDER=openai
echo        OPENAI_API_KEY=sk-...
echo        OPENAI_MODEL=gpt-4o-mini
echo        OPENAI_BASE_URL=https://api.openai.com/v1
echo      Har case me:
echo        DEVICE_TOKENS=replace-with-your-private-device-token

echo        Use the same private token only in a privately paired APK. Never put it in this setup script or a public source archive.
echo   2) run_windows.bat  (server chalu karega)
echo.
echo Aapka laptop ka IP (phone me SERVER_URL ke liye - Wi-Fi wali line):
ipconfig | findstr /i "IPv4"
echo.
echo (Itni hi zaroorat hai. Detailed guide: ..\SERVER_SETUP_Hinglish.md)
echo ======================================================
pause
exit /b 0

:nopython
echo [X] Python nahi mila.
echo     python.org se Python 3.11+ install karo aur installer me
echo     "Add python.exe to PATH" wala box ZAROOR tick karo.
pause
exit /b 1

:fail
echo [X] Setup beech me fail ho gaya - upar ka error message dekho.
pause
exit /b 1
