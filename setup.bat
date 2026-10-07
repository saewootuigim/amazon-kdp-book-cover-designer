@echo off
rem (Re)create the project-local virtual environment and install everything into it.
rem The pip cache and pip config also stay inside this folder.
setlocal
cd /d "%~dp0"
set "PIP_CACHE_DIR=%~dp0.pip-cache"
set "PIP_CONFIG_FILE=%~dp0.venv\pip.ini"
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv || python -m venv .venv || goto :fail
)
> .venv\pip.ini echo [global]
>> .venv\pip.ini echo cache-dir = %~dp0.pip-cache
.venv\Scripts\python.exe -m pip install --isolated --cache-dir "%PIP_CACHE_DIR%" --upgrade pip || goto :fail
.venv\Scripts\python.exe -m pip install --isolated --cache-dir "%PIP_CACHE_DIR%" -r requirements.txt || goto :fail
echo.
echo Done. Start the app with run.bat
exit /b 0
:fail
echo Setup failed.
exit /b 1
