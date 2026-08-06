@echo off
chcp 65001 >nul
echo ========================================
echo   创建桌面快捷方式
echo ========================================
echo.

set SCRIPT_DIR=%~dp0
set TARGET_BAT=%SCRIPT_DIR%CNC_AI_Brain_启动.bat
set DESKTOP=%USERPROFILE%\Desktop
set SHORTCUT_NAME=CNC AI Brain 启动.lnk

echo 正在创建桌面快捷方式...

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%DESKTOP%\%SHORTCUT_NAME%'); $s.TargetPath = '%TARGET_BAT%'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Description = 'OPC CNC AI Brain v11.1.0 一键启动'; $s.Save()"

if exist "%DESKTOP%\%SHORTCUT_NAME%" (
    echo.
    echo ✅ 桌面快捷方式创建成功！
    echo    位置: %DESKTOP%\%SHORTCUT_NAME%
    echo.
    echo 双击桌面图标即可启动 CNC AI Brain
) else (
    echo.
    echo ❌ 创建失败，请手动创建快捷方式
    echo    目标: %TARGET_BAT%
)

echo.
pause
