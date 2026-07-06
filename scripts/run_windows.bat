@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ============================================================
:: 轻量化桌面AI效率助手 - Windows 开发运行脚本
:: 用法：双击此文件，或在项目根目录 cmd 中执行
:: 脚本会自动创建/激活虚拟环境、安装依赖并启动程序
:: ============================================================

:: 切换到脚本所在目录的上一级（即项目根目录）
cd /d "%~dp0.."

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║       轻量化桌面AI效率助手 - 启动脚本           ║
echo ║       项目目录：%CD%
echo ╚══════════════════════════════════════════════════╝
echo.

:: ── 步骤1：检查 Python 是否安装 ──────────────────────────────
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

:: ── 步骤2：创建或复用虚拟环境 ────────────────────────────────
echo.
echo [2/6] 检查虚拟环境 .venv ...
if exist ".venv\Scripts\activate.bat" (
    echo    ✅ 虚拟环境已存在，直接使用
) else (
    echo    ⏳ 虚拟环境不存在，正在创建 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ❌ 创建虚拟环境失败！请检查 Python 是否正常安装。
        echo.
        pause
        exit /b 1
    )
    echo    ✅ 虚拟环境创建完成
)

:: ── 步骤3：激活虚拟环境 ──────────────────────────────────────
echo.
echo [3/6] 激活虚拟环境...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo.
    echo ❌ 激活虚拟环境失败！请检查 .venv 目录是否完整。
    echo.
    pause
    exit /b 1
)
echo    ✅ 虚拟环境已激活

:: ── 步骤4：升级 pip ───────────────────────────────────────────
echo.
echo [4/6] 升级 pip...
python -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo    ⚠️  pip 升级失败（可忽略，继续安装依赖）
) else (
    echo    ✅ pip 已升级到最新版本
)

:: ── 步骤5：安装基础依赖 ──────────────────────────────────────
echo.
echo [5/6] 安装基础依赖 requirements-base.txt ...
if not exist "requirements-base.txt" (
    echo    ⚠️  未找到 requirements-base.txt，跳过
) else (
    pip install -r requirements-base.txt
    if errorlevel 1 (
        echo.
        echo ❌ 安装基础依赖失败！请检查网络连接或 requirements-base.txt 内容。
        echo    可尝试手动运行：pip install -r requirements-base.txt
        echo.
        pause
        exit /b 1
    )
    echo    ✅ 基础依赖安装完成
)

:: ── 步骤6：安装 Windows 专属依赖 ─────────────────────────────
echo.
echo [6/6] 安装 Windows 专属依赖 requirements-win.txt ...
if not exist "requirements-win.txt" (
    echo    ⚠️  未找到 requirements-win.txt，跳过
) else (
    pip install -r requirements-win.txt
    if errorlevel 1 (
        echo.
        echo ❌ 安装 Windows 专属依赖失败！
        echo    可尝试手动运行：pip install -r requirements-win.txt
        echo.
        pause
        exit /b 1
    )
    echo    ✅ Windows 专属依赖安装完成
)

:: ── 启动程序 ──────────────────────────────────────────────────
echo.
echo ══════════════════════════════════════════════════
echo    ✅ 所有依赖已就绪，正在启动助手...
echo ══════════════════════════════════════════════════
echo.

python main.py
if errorlevel 1 (
    echo.
    echo ❌ 程序运行出错（退出代码：%errorlevel%）
    echo    请查看上方错误信息，或检查 data/app.log 日志文件。
    echo.
    pause
    exit /b 1
)

endlocal
