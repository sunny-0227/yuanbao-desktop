"""
系统控制服务：音量控制 + 锁屏
包含 VolumeService 和 SystemCommandService。

设计原则：
- 所有 Windows 专属逻辑均通过 platform.system() 判断后执行
- 音量控制在 Windows 上使用 pycaw；未安装时提示用户安装
- 锁屏在 Windows 上使用 ctypes，macOS 使用 pmset
- 非 Windows 环境静默降级，返回提示而非崩溃
- 所有异常被捕获，返回友好字符串
"""

import platform
import subprocess
from app.logger import setup_logger

logger = setup_logger()

_SYSTEM = platform.system()


# ── 音量服务 ──────────────────────────────────────────────────

class VolumeService:
    """
    音量控制服务（Windows 专属，macOS/Linux 提示不支持）。

    Windows 上使用 pycaw；未安装 pycaw 时提示用户安装。
    所有方法返回字符串，供聊天窗口直接展示。
    """

    def _get_volume_ctrl(self):
        """
        获取 Windows 音量控制接口。
        返回 (ISimpleAudioVolume 实例, None) 或 (None, 错误字符串)
        """
        if _SYSTEM != "Windows":
            return None, "音量控制仅支持 Windows 环境。"
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore[import]
            from comtypes import CLSCTX_ALL  # type: ignore[import]
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            return volume, None
        except ImportError:
            msg = (
                "音量控制功能需要安装 pycaw，请运行：\n"
                "  pip install pycaw"
            )
            return None, msg
        except Exception as e:
            logger.error(f"获取音量控制接口失败：{e}")
            return None, f"⚠️ 音量控制接口初始化失败：{e}"

    def mute(self) -> str:
        """静音"""
        vol, err = self._get_volume_ctrl()
        if err:
            return f"⚠️ {err}"
        try:
            vol.SetMute(1, None)
            logger.debug("已静音")
            return "🔇 已静音。"
        except Exception as e:
            logger.error(f"静音失败：{e}")
            return f"⚠️ 静音失败：{e}"

    def unmute(self) -> str:
        """取消静音"""
        vol, err = self._get_volume_ctrl()
        if err:
            return f"⚠️ {err}"
        try:
            vol.SetMute(0, None)
            logger.debug("已取消静音")
            return "🔊 已取消静音。"
        except Exception as e:
            logger.error(f"取消静音失败：{e}")
            return f"⚠️ 取消静音失败：{e}"

    def volume_up(self, step: float = 0.1) -> str:
        """增大音量（默认 +10%）"""
        vol, err = self._get_volume_ctrl()
        if err:
            return f"⚠️ {err}"
        try:
            current = vol.GetMasterVolumeLevelScalar()
            new_vol = min(1.0, current + step)
            vol.SetMasterVolumeLevelScalar(new_vol, None)
            logger.debug(f"音量调高：{current:.0%} → {new_vol:.0%}")
            return f"🔊 音量已调高至 {new_vol:.0%}。"
        except Exception as e:
            logger.error(f"调高音量失败：{e}")
            return f"⚠️ 调高音量失败：{e}"

    def volume_down(self, step: float = 0.1) -> str:
        """降低音量（默认 -10%）"""
        vol, err = self._get_volume_ctrl()
        if err:
            return f"⚠️ {err}"
        try:
            current = vol.GetMasterVolumeLevelScalar()
            new_vol = max(0.0, current - step)
            vol.SetMasterVolumeLevelScalar(new_vol, None)
            logger.debug(f"音量调低：{current:.0%} → {new_vol:.0%}")
            return f"🔉 音量已调低至 {new_vol:.0%}。"
        except Exception as e:
            logger.error(f"调低音量失败：{e}")
            return f"⚠️ 调低音量失败：{e}"


# ── 系统命令服务 ──────────────────────────────────────────────

class SystemCommandService:
    """
    系统控制服务（锁屏等）。

    Windows 使用 ctypes.windll.user32.LockWorkStation()；
    macOS 使用 pmset displaysleepnow（近似效果）；
    Linux 使用 loginctl lock-session。

    所有方法返回字符串，供聊天窗口直接展示。
    """

    def lock_screen(self) -> str:
        """锁定屏幕"""
        try:
            if _SYSTEM == "Windows":
                import ctypes
                ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
                logger.debug("Windows 锁屏已触发")
                return "🔒 屏幕已锁定。"
            elif _SYSTEM == "Darwin":
                subprocess.Popen(
                    ["/usr/bin/pmset", "displaysleepnow"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.debug("macOS 显示器休眠已触发")
                return "🔒 显示器已关闭（macOS 近似锁屏）。"
            else:
                subprocess.Popen(
                    ["loginctl", "lock-session"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.debug("Linux 锁屏已触发")
                return "🔒 屏幕已锁定。"
        except Exception as e:
            logger.error(f"锁屏失败：{e}")
            return f"⚠️ 锁屏失败：{e}"
