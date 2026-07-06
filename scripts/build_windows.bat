@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ============================================================
:: 轻量化桌面AI效率助手 - Windows exe 打包脚本
:: 使用 PyInstaller 将项目打包为单文件 exe
:: 用法：双击此文件，或在项目根目录 cmd 中执行
:: ============================================================

:: 切换到脚本所在目录的上一级（即项目根目录），路径不写死
cd /d "%~dp0.."

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║      轻量化桌面AI效率助手 - EXE 打包脚本        ║
echo ║      项目目录：%CD%
echo ╚══════════════════════════════════════════════════╝
echo.

:: ── 步骤1：检查 Python ───────────────────────────────────────
echo [1/6] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ❌ 未检测到 Python！请先安装 Python 3.11 或更高版本。
    echo    下载地址：https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo    ✅ 检测到 %%v

:: ── 步骤2：检查虚拟环境并激活 ───────────────────────────────
echo.
echo [2/6] 检查并激活虚拟环境...
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    echo    ✅ 已激活虚拟环境 .venv
) else (
    echo    ℹ️  未找到 .venv，将使用系统 Python 环境
    echo    建议先运行 scripts\run_windows.bat 创建虚拟环境
)

:: ── 步骤3：检查 PyInstaller 是否已安装 ──────────────────────
echo.
echo [3/6] 检查 PyInstaller...
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ❌ 未检测到 PyInstaller！
    echo    请先安装 Windows 专属依赖：
    echo      pip install -r requirements-win.txt
    echo    或直接安装：
    echo      pip install pyinstaller
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('pyinstaller --version 2^>^&1') do echo    ✅ PyInstaller 版本：%%v

:: ── 步骤4：检查图标文件，构造 --icon 参数 ───────────────────
echo.
echo [4/6] 检查打包资源...

set ICON_ARG=
if exist "assets\icons\app_icon.ico" (
    set ICON_ARG=--icon "assets\icons\app_icon.ico"
    echo    ✅ 找到应用图标：assets\icons\app_icon.ico
) else if exist "assets\icons\app.ico" (
    set ICON_ARG=--icon "assets\icons\app.ico"
    echo    ✅ 找到应用图标：assets\icons\app.ico
) else (
    echo    ⚠️  未找到 assets\icons\app_icon.ico，将使用 PyInstaller 默认图标
    echo       如需自定义图标，请将 app_icon.ico 放到 assets\icons\ 目录
)

:: 检查 .env.example（缺失时跳过该资源，不阻止打包）
set DOTENV_ARG=
if exist ".env.example" (
    set DOTENV_ARG=--add-data ".env.example;."
    echo    ✅ 找到 .env.example
) else (
    echo    ⚠️  未找到 .env.example，跳过打包该文件
)

:: 检查 data 目录
if exist "data" (
    echo    ✅ 找到 data 目录
) else (
    echo    ⚠️  未找到 data 目录，将跳过（运行时自动创建）
)

:: 检查 assets 目录
if exist "assets" (
    echo    ✅ 找到 assets 目录
) else (
    echo    ⚠️  未找到 assets 目录，宠物图片等资源将缺失
)

:: ── 步骤5：清理旧的构建产物 ──────────────────────────────────
echo.
echo [5/6] 清理旧的 build / dist 目录...
if exist "build" (
    rmdir /s /q "build"
    echo    🗑️  已删除旧的 build 目录
)
if exist "dist" (
    rmdir /s /q "dist"
    echo    🗑️  已删除旧的 dist 目录
)
if exist "TutuAssistant.spec" (
    del /q "TutuAssistant.spec"
    echo    🗑️  已删除旧的 TutuAssistant.spec
)
echo    ✅ 清理完成

:: ── 步骤6：执行 PyInstaller 打包 ────────────────────────────
echo.
echo [6/6] 开始打包，请稍候（可能需要 1~3 分钟）...
echo ──────────────────────────────────────────────────
echo.

:: 构造打包命令（分行书写，使用 ^ 续行，增强可读性）
:: --onefile     打包为单个 exe
:: --noconsole   不显示控制台窗口（GUI 程序必须）
:: --add-data    打包资源目录，Windows 下分隔符为分号
pyinstaller ^
    --onefile ^
    --noconsole ^
    --name TutuAssistant ^
    %ICON_ARG% ^
    --add-data "assets;assets" ^
    --add-data "data;data" ^
    --add-data "config.json;." ^
    %DOTENV_ARG% ^
    --hidden-import PySide6.QtSvg ^
    --hidden-import PySide6.QtXml ^
    --hidden-import httpx ^
    --hidden-import psutil ^
    --hidden-import PIL ^
    --hidden-import PIL.ImageGrab ^
    --hidden-import pycaw.pycaw ^
    --hidden-import comtypes ^
    --hidden-import comtypes.client ^
    main.py

if errorlevel 1 (
    echo.
    echo ══════════════════════════════════════════════════
    echo ❌ 打包失败！请查看上方 PyInstaller 输出的错误信息。
    echo    常见原因：
    echo      1. 缺少依赖包 → 先运行 scripts\run_windows.bat 安装依赖
    echo      2. main.py 存在语法错误 → 先用 python main.py 验证
    echo      3. 资源路径不存在 → 检查 assets / data / config.json
    echo ══════════════════════════════════════════════════
    echo.
    pause
    exit /b 1
)

:: ── 打包成功提示 ──────────────────────────────────────────────
echo.
echo ══════════════════════════════════════════════════
echo ✅ 打包完成！
echo    exe 路径：dist\TutuAssistant.exe
echo.
echo    运行前请确保：
echo      1. 将 .env 文件复制到 exe 同目录（AI 功能需要）
echo      2. 首次运行会在同目录自动创建 data 目录
echo ══════════════════════════════════════════════════
echo.

:: 询问是否立即运行
set /p RUN_NOW=是否立即运行 TutuAssistant.exe？[y/N] 
if /i "!RUN_NOW!"=="y" (
    echo 正在启动...
    start "" "dist\TutuAssistant.exe"
)

pause
endlocal
