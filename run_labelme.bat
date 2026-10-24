@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ============================================================
rem  labelme custom build - launcher
rem
rem  Walks a list of candidate interpreters and uses the FIRST one
rem  that can import every dependency. A venv is not required; a
rem  venv is just one of the candidates.
rem
rem  Candidate order:
rem    1. %LABELME_PYTHON%
rem    2. python_path.txt   (one line: full path to python.exe)
rem    3. .venv / venv / env next to this file
rem    4. python / python3 / py -3 from PATH
rem ============================================================

set "CAND1="
if defined LABELME_PYTHON set "CAND1=%LABELME_PYTHON%"

set "CAND2="
if exist "%~dp0python_path.txt" set /p CAND2=<"%~dp0python_path.txt"
if defined CAND2 set "CAND2=%CAND2:"=%"

set "CAND3=%~dp0.venv\Scripts\python.exe"
set "CAND4=%~dp0venv\Scripts\python.exe"
set "CAND5=%~dp0env\Scripts\python.exe"
set "CAND6=python"
set "CAND7=python3"
set "CAND8=py -3"

set "PYCMD="
set "PYDISP="
set "TRIED="
set "DIAG="
set "DIAGQ="

echo [labelme] looking for a usable Python ...
for %%I in (1 2 3 4 5 6 7 8) do (
    if not defined PYCMD call :trycand "!CAND%%I!"
)

if not defined PYCMD goto no_deps

echo [labelme] interpreter: %PYDISP%
echo [labelme] starting ...
rem relative script path: the folder name may contain non-ASCII
rem characters, which some code pages truncate in absolute paths
call %PYCMD% start_custom_labelme.py
if errorlevel 1 goto run_failed
exit /b 0


rem ------------------------------------------------------------
rem  :trycand <candidate>
rem  Accepts a candidate only if it really imports every module.
rem  Also remembers the first existing one for the diagnostics.
rem ------------------------------------------------------------
:trycand
set "C=%~1"
if not defined C exit /b 0
set "QC=%C%"
rem a drive letter means it is a path: must exist, and needs quotes
if "%C:~1,1%"==":" (
    if not exist "%C%" exit /b 0
    set "QC="%C%""
    if not defined DIAG (
        set "DIAG=%C%"
        set "DIAGQ="%C%""
    )
)
set "TRIED=%TRIED% "%C%""
rem Dependency check: delegate to check_deps.py --quiet.
rem Do NOT keep a second hardcoded import list here - it drifted before
rem (missing PIL / qtpy / torchvision) and accepted interpreters that then
rem failed at startup. check_deps.py is the single source of truth, and it
rem also rejects Python < 3.7 before anything is imported.
call %QC% check_deps.py --quiet >nul 2>nul
if errorlevel 1 (
    if not defined DIAG (
        set "DIAG=%C%"
        set "DIAGQ=%QC%"
    )
    exit /b 0
)
set "PYCMD=%QC%"
set "PYDISP=%C%"
exit /b 0


:no_deps
echo.
echo [ERROR] 下列 Python 都无法导入全部依赖：
echo.
echo            %TRIED%
echo.
echo ============================================================
echo  现在逐项检查最能用的那个解释器，看具体缺什么
echo ============================================================
echo.
if not defined DIAG goto no_hint
call %DIAGQ% check_deps.py
goto no_hint_end

:no_hint
echo   （没能找到可用于检查的解释器）
echo   可用下面的命令手工安装依赖：
echo.
echo        python -m pip install -r requirements.txt

:no_hint_end
echo.
echo ============================================================
echo  两种让本脚本找到正确解释器的办法
echo ============================================================
echo.
echo   1) 在 python_path.txt 里写一行 python.exe 的完整路径，例如
echo.
echo          D:/venvs/labelme/Scripts/python.exe
echo.
echo   2) 或临时设一个环境变量再运行：
echo.
echo          set LABELME_PYTHON=D:/venvs/labelme/Scripts/python.exe
echo          run_labelme.bat
echo.
pause
exit /b 1


:run_failed
echo.
echo [ERROR] labelme exited with code %errorlevel%.
echo.
echo   If a Python traceback appeared above, read that first - it is the
echo   real cause.
echo.
echo   If there is NO traceback, most likely the process was ended from
echo   outside instead of being closed normally:
echo       - Ctrl+C in this window
echo       - Task Manager / killed by a script or a timeout wrapper
echo       - the terminal window itself was closed
echo   None of these mean the program is broken.
echo.
echo   Only when the window never appeared at all, check:
echo       - model weights missing   (README section 6)
echo       - torch / GPU build mismatch
echo.
echo   Closing the labelme window with the X button is normal and never
echo   reaches this message.
echo.
pause
exit /b 1
