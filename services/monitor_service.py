"""
系统状态监测服务（辅助功能）
查询 CPU / 内存 / 硬盘 / 电池等基本系统信息，

设计原则：
- 使用 psutil 跨平台获取系统信息，未安装时提示用户安装
- 设备状态查询为辅助功能，不作为核心功能
- 电池状态在台式机上会优雅降级
- 所有异常被捕获，返回友好字符串或默认安全值，不向上抛出
"""

import platform

from app.logger import setup_logger

logger = setup_logger()


def _require_psutil():
    """导入 psutil，未安装时抛出友好的 ImportError 消息"""
    try:
        import psutil  # type: ignore[import]

        return psutil
    except ImportError as exc:
        raise ImportError("系统监测功能需要安装 psutil，请运行：\n  pip install psutil") from exc


class MonitorService:
    """
    系统状态监测服务（辅助功能）。

    返回系统状态的格式化文本；自动休眠由独立采样服务负责。
    """

    # ── 面向聊天窗口的展示方法 ────────────────────────────────

    def check_all(self) -> str:
        """一次性返回 CPU、内存、磁盘概览"""
        parts = []
        parts.append(self.check_cpu())
        parts.append(self.check_memory())
        parts.append(self.check_disk())
        battery = self.check_battery()
        if "不支持" not in battery and "失败" not in battery:
            parts.append(battery)
        return "\n".join(parts)

    def check_cpu(self) -> str:
        """查询当前 CPU 使用率"""
        try:
            psutil = _require_psutil()
            usage = psutil.cpu_percent(interval=0.5)
            return f"🖥️ CPU 使用率：{usage:.1f}%"
        except ImportError as e:
            return f"⚠️ {e}"
        except Exception as e:
            logger.error(f"CPU 查询失败：{e}")
            return f"⚠️ CPU 查询失败：{e}"

    def check_memory(self) -> str:
        """查询当前内存使用情况"""
        try:
            psutil = _require_psutil()
            mem = psutil.virtual_memory()
            total_gb = mem.total / (1024**3)
            used_gb = mem.used / (1024**3)
            return (
                f"💾 内存：已用 {used_gb:.1f} GB / 共 {total_gb:.1f} GB"
                f"（使用率 {mem.percent:.1f}%）"
            )
        except ImportError as e:
            return f"⚠️ {e}"
        except Exception as e:
            logger.error(f"内存查询失败：{e}")
            return f"⚠️ 内存查询失败：{e}"

    def check_disk(self, path: str = "/") -> str:
        """查询指定路径的磁盘使用情况，Windows 默认查询 C:\\"""
        try:
            psutil = _require_psutil()
            if platform.system() == "Windows" and path == "/":
                path = "C:\\"
            disk = psutil.disk_usage(path)
            total_gb = disk.total / (1024**3)
            used_gb = disk.used / (1024**3)
            return (
                f"💿 磁盘（{path}）：已用 {used_gb:.1f} GB / 共 {total_gb:.1f} GB"
                f"（使用率 {disk.percent:.1f}%）"
            )
        except ImportError as e:
            return f"⚠️ {e}"
        except Exception as e:
            logger.error(f"磁盘查询失败：{e}")
            return f"⚠️ 磁盘查询失败：{e}"

    def check_battery(self) -> str:
        """查询电池电量（台式机会提示不支持）"""
        try:
            psutil = _require_psutil()
            battery = psutil.sensors_battery()
            if battery is None:
                return "🔌 未检测到电池（可能是台式机或不支持此查询）"
            percent = battery.percent
            plugged = "已充电" if battery.power_plugged else "未充电"
            return f"🔋 电池：{percent:.0f}%，{plugged}"
        except ImportError as e:
            return f"⚠️ {e}"
        except Exception as e:
            logger.error(f"电池查询失败：{e}")
            return f"⚠️ 电池查询失败：{e}"
