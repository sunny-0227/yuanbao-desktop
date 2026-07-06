"""
PyInstaller 打包脚本（在 Windows 上执行）
用法：python scripts/build_exe.py
"""

import os
import sys
import subprocess
import shutil

# 项目根目录（脚本的上一级）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT_DIR, "dist")
BUILD_DIR = os.path.join(ROOT_DIR, "build")

# exe 输出名称
APP_NAME = "TutuAI"

# 需要打包进 exe 的额外数据目录（源路径, 目标路径）
DATAS = [
    (os.path.join(ROOT_DIR, "assets"), "assets"),
    (os.path.join(ROOT_DIR, "config.json"), "."),
    # 指令规则配置，运行时由 CommandRouter 读取
    (os.path.join(ROOT_DIR, "data", "command_rules.json"), "data"),
]

# Windows 专属图标路径
ICON_PATH = os.path.join(ROOT_DIR, "assets", "icons", "app_icon.ico")


def build():
    """执行 PyInstaller 打包"""
    if sys.platform != "win32":
        print("⚠️  此脚本只能在 Windows 上运行")
        sys.exit(1)

    # 确认 PyInstaller 可用
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("未找到 PyInstaller，请先运行：pip install pyinstaller")
        sys.exit(1)

    # 清理上次构建产物
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"已清理：{d}")

    # 构建 --add-data 参数列表
    add_data_args = []
    for src, dst in DATAS:
        if os.path.exists(src):
            add_data_args += ["--add-data", f"{src};{dst}"]
        else:
            print(f"[警告] 资源不存在，跳过：{src}")

    # 图标参数
    icon_args = []
    if os.path.exists(ICON_PATH):
        icon_args = ["--icon", ICON_PATH]
    else:
        print(f"[警告] 图标文件不存在，跳过：{ICON_PATH}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",           # 打成单个 exe
        "--windowed",          # 不显示控制台窗口
        "--name", APP_NAME,
        *icon_args,
        *add_data_args,
        os.path.join(ROOT_DIR, "main.py"),
    ]

    print("开始打包…")
    print("命令：", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT_DIR)

    if result.returncode == 0:
        exe_path = os.path.join(DIST_DIR, f"{APP_NAME}.exe")
        print(f"\n✅ 打包成功！输出：{exe_path}")
    else:
        print(f"\n❌ 打包失败，退出码：{result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
