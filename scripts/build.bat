@echo off
REM Windows 一键安装依赖并打包脚本
REM 使用方法：双击运行或在 cmd 中执行

echo ========================================
echo  轻量化桌面AI虚拟助手 - 构建工具
echo ========================================

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)

echo [1/3] 安装基础依赖...
pip install -r requirements-base.txt
if errorlevel 1 (
    echo [错误] 安装 requirements-base.txt 失败
    pause
    exit /b 1
)

echo [2/3] 安装 Windows 专属依赖...
pip install -r requirements-win.txt
if errorlevel 1 (
    echo [错误] 安装 requirements-win.txt 失败
    pause
    exit /b 1
)

echo [3/3] 开始打包 exe...
python scripts\build_exe.py
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo 构建完成！exe 文件在 dist\ 目录中
pause
