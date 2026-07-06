"""
应用上下文模块 - 统一资源路径管理

为什么需要兼容 sys._MEIPASS？
    PyInstaller 打包时会把所有 Python 文件和资源压缩进一个 exe。
    运行时 exe 会把资源解压到一个临时目录，该目录路径存储在 sys._MEIPASS。
    如果直接用 __file__ 或 os.getcwd() 拼路径，打包后会找不到资源文件。
    因此所有涉及资源读取的路径都必须经过本模块的 resource_path() 转换。

路径说明（打包 vs 源码运行）：
    resource_path()  只读资源（assets/、config.json 等），打包后从 _MEIPASS 读取
    data_path()      可写用户数据（data/*.json、app.log 等），始终指向 exe 旁边目录
                     打包后若写入 _MEIPASS 会在重启时丢失，因此需单独处理

使用方式：
    from app.app_context import resource_path, data_path
    img   = resource_path("assets/pet/idle.png")   # 只读资源
    notes = data_path("data/notes.json")            # 可写数据
"""

import os
import sys


def get_base_path() -> str:
    """
    获取只读资源根目录。

    - 打包后（exe 运行）：sys._MEIPASS 是 PyInstaller 的临时解压目录，
      assets、config.json 等只读文件都在此目录下。
    - 源码运行：使用本文件所在 app/ 的上级目录，即项目根目录。

    返回：只读资源根目录的绝对路径字符串
    """
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller 单文件打包模式：资源被解压到临时目录
        return sys._MEIPASS  # type: ignore[attr-defined]

    # 源码运行：app_context.py 在 app/ 下，取上一级即项目根目录
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_data_base_path() -> str:
    """
    获取用户数据根目录（可写）。

    打包后，用户数据应存储在 exe 所在目录旁（而非 _MEIPASS 临时目录），
    这样数据才能在重启后保留。
    源码运行时与 get_base_path() 相同（项目根目录）。

    返回：可写数据根目录的绝对路径字符串
    """
    if hasattr(sys, "_MEIPASS"):
        # 打包后：使用 exe 所在目录，而不是临时解压目录
        return os.path.dirname(sys.executable)

    # 源码运行：项目根目录
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path: str) -> str:
    """
    将相对路径转换为只读资源的绝对路径。
    用于读取 assets/、config.json 等随 exe 一起打包的只读文件。

    参数：
        relative_path: 相对于项目根目录的路径，例如：
            "config.json"
            "assets/icons/app_icon.ico"
            "assets/pet/idle.png"

    返回：对应的绝对路径字符串
    """
    normalized = os.path.normpath(relative_path)
    return os.path.join(get_base_path(), normalized)


def data_path(relative_path: str) -> str:
    """
    将相对路径转换为用户可写数据文件的绝对路径。
    用于 data/*.json、app.log 等需要持久化的用户数据。
    打包后数据存储在 exe 同目录（而非 _MEIPASS），重启后数据不丢失。

    参数：
        relative_path: 相对路径，例如：
            "data/notes.json"
            "data/app.log"

    返回：对应的绝对路径字符串
    """
    normalized = os.path.normpath(relative_path)
    return os.path.join(get_data_base_path(), normalized)
