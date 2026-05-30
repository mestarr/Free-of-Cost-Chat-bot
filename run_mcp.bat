@echo off
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
  venv\Scripts\python.exe -m backend.mcp_server
) else (
  python -m backend.mcp_server
)
