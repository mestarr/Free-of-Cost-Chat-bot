@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo No venv found. Create it with: py -3 -m venv venv
  echo Then run: venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)
"%~dp0venv\Scripts\python.exe" -m uvicorn backend.main:app --reload
exit /b %ERRORLEVEL%
