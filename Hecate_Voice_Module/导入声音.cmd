@echo off
chcp 65001 >nul
set "voiceHome=%~dp0..\启动版\可选模块\voice_engine"
if not exist "%voiceHome%\runtime\python.exe" (
  echo 请先在工作台模块中心安装本地文字转语音模块。
  pause
  exit /b 1
)
cd /d "%voiceHome%"
"%voiceHome%\runtime\python.exe" -B -X utf8 "%voiceHome%\model_importer.py" %*
echo.
pause
