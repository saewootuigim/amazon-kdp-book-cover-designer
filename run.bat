@echo off
rem Launch Book Cover Editor using the project-local virtual environment.
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo The virtual environment is missing. Run setup.bat first.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
