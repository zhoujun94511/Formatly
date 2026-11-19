@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "FORMATLY_LAUNCH_PYTHON="
set "FORMATLY_LAUNCH_ARGS="

if exist "%~dp0.venv\Scripts\python.exe" (
  set "FORMATLY_LAUNCH_PYTHON=%~dp0.venv\Scripts\python.exe"
  goto validate_python
)
where python >nul 2>nul
if not errorlevel 1 (
  set "FORMATLY_LAUNCH_PYTHON=python"
  goto validate_python
)
where py >nul 2>nul
if not errorlevel 1 (
  set "FORMATLY_LAUNCH_PYTHON=py"
  set "FORMATLY_LAUNCH_ARGS=-3"
  goto validate_python
)
echo 未找到 Python。请安装 Python 3.11 或更高版本，并将其加入 PATH。
pause
exit /b 2

:validate_python
"%FORMATLY_LAUNCH_PYTHON%" %FORMATLY_LAUNCH_ARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Formatly 需要 Python 3.11 或更高版本。请检查当前 Python 或项目 .venv 环境。
  pause
  exit /b 2
)
"%FORMATLY_LAUNCH_PYTHON%" %FORMATLY_LAUNCH_ARGS% "%~dp0app.py" %*
if errorlevel 1 (
  echo Formatly 启动失败，请查看上方错误信息。
  pause
  exit /b 2
)
exit /b 0

