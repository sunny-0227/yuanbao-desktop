"""
截图服务
使用 Pillow（PIL）截取全屏并保存到配置目录。

设计原则：
- 仅在 Windows 上执行截图（PIL ImageGrab.grab 依赖 Windows/macOS API）
- 保存目录取自 ScreenshotConfig.resolved_save_dir()
- 截图文件名格式：screenshot_YYYYMMDD_HHMMSS.png
- auto_open=True 时截图后自动用系统图片查看器打开
- 所有异常被捕获，返回友好字符串，不向上抛出
- 未安装 Pillow 时提示用户安装，不崩溃
"""

import os
import platform
from datetime import datetime
from pathlib import Path

from app.logger import setup_logger

logger = setup_logger()


class ScreenshotService:
    """
    截图服务。

    实例化时传入 ScreenshotConfig，为空时使用默认目录。

    所有 public 方法返回字符串，供聊天窗口直接展示。
    """

    def __init__(self, config=None):
        self._config = config

    def _get_save_dir(self) -> str:
        if self._config:
            return self._config.resolved_save_dir()
        # 默认目录：跨平台使用 Path.home()，避免 %USERPROFILE% 在 macOS/Linux 不展开
        return str(Path.home() / "Pictures" / "YuanbaoScreenshots")

    def _get_fmt(self) -> str:
        if self._config:
            return self._config.format or "png"
        return "png"

    def _auto_open(self) -> bool:
        return bool(self._config and self._config.auto_open)

    def take_screenshot(self) -> str:
        """
        截取全屏并保存到配置目录。
        仅支持 Windows 和 macOS；Linux 下提示不支持。
        """
        system = platform.system()
        if system == "Linux":
            return "⚠️ Linux 暂不支持截图功能。"

        try:
            from PIL import ImageGrab  # type: ignore[import]
        except ImportError:
            return "⚠️ 截图功能需要安装 Pillow，请运行：\n  pip install Pillow"

        try:
            save_dir = self._get_save_dir()
            os.makedirs(save_dir, exist_ok=True)

            fmt = self._get_fmt()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.{fmt}"
            filepath = os.path.join(save_dir, filename)

            img = ImageGrab.grab()
            img.save(filepath)
            logger.debug(f"截图已保存：{filepath}")

            result = f"截图已保存：{filepath}"

            if self._auto_open():
                try:
                    if system == "Windows" and hasattr(os, "startfile"):
                        os.startfile(filepath)  # type: ignore[attr-defined]
                    elif system == "Darwin":
                        import subprocess

                        subprocess.Popen(["open", filepath])
                except Exception as e:
                    logger.warning(f"自动打开截图失败：{e}")

            return result

        except Exception as e:
            logger.error(f"截图失败：{e}")
            return f"⚠️ 截图失败：{e}"
