"""平台检测。"""

import platform


def is_windows() -> bool:
    """判断当前运行环境是否为 Windows"""
    return platform.system() == "Windows"
