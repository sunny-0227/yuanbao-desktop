"""
通用工具函数
包含平台检测和目录初始化等与业务无关的辅助方法。

注意：资源路径相关功能已统一迁移至 app/app_context.py，
本模块不再提供路径拼接函数，避免多套路径逻辑并存。
"""

import sys
import os
import platform


def is_windows() -> bool:
    """判断当前运行环境是否为 Windows"""
    return platform.system() == "Windows"


def is_packaged() -> bool:
    """判断当前是否以 PyInstaller 打包后的 exe 形式运行"""
    return hasattr(sys, "_MEIPASS")


def ensure_dirs():
    """
    确保运行时所需目录存在（应用启动时调用一次）。
    使用 resource_path 保证打包后路径也能正确创建。
    """
    from app.app_context import resource_path
    dirs = [resource_path("data")]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
