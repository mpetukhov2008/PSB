@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PSB_SELECTED="
if defined PSB_PYTHON (
    call :try_python "%PSB_PYTHON%"
    if not defined PSB_SELECTED goto no_python
    goto launch
)
where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        py -3 -m psb.launcher %*
        goto finished
    )
)
for /f "delims=" %%P in ('where python.exe python3.exe 2^>nul') do call :try_python "%%P"
for /d %%D in ("%LocalAppData%\Programs\Python\Python*" "%ProgramFiles%\Python*") do call :try_python "%%~D\python.exe"
call :try_python "C:\msys64\ucrt64\bin\python.exe"
if not defined PSB_SELECTED goto no_python
:launch
"%PSB_SELECTED%" -m psb.launcher %*
goto finished
:no_python
echo Python 3.10+ was not found. Install Python from https://www.python.org/downloads/
echo Or set PSB_PYTHON to the full path of your python.exe. See README.md.
set "PSB_EXIT=1"
goto finish_with_code
:finished
set "PSB_EXIT=%ERRORLEVEL%"
:finish_with_code
if not "%PSB_EXIT%"=="0" if "%~1"=="" pause
exit /b %PSB_EXIT%
:try_python
if defined PSB_SELECTED exit /b
if not exist "%~1" exit /b
echo "%~1" | find /i "WindowsApps" >nul
if not errorlevel 1 exit /b
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 exit /b
set "PSB_SELECTED=%~1"
exit /b
