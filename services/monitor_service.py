"""
系统状态监测服务（辅助功能）
查询 CPU / 内存 / 硬盘 / 电池等基本系统信息，
同时提供供自动休眠逻辑调用的数值型方法。

设计原则：
- 使用 psutil 跨平台获取系统信息，未安装时提示用户安装
- 设备状态查询为辅助功能，不作为核心功能
- 电池状态在台式机上会优雅降级
- 所有异常被捕获，返回友好字符串或默认安全值，不向上抛出
"""

import platform
from typing import Optional

from app.logger import setup_logger

logger = setup_logger()


def _require_psutil():
    """导入 psutil，未安装时抛出友好的 ImportError 消息"""
    try:
        import psutil  # type: ignore[import]
        return psutil
    except ImportError:
        raise ImportError(
            "系统监测功能需要安装 psutil，请运行：\n"
            "  pip install psutil"
        )


class MonitorService:
    """
    系统状态监测服务（辅助功能）。

    公开两类方法：
      - check_*()        返回格式化字符串，供聊天窗口展示
      - get_*()          返回纯数值/列表，供自动休眠逻辑（AutoSleepService）判断
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
            total_gb = mem.total / (1024 ** 3)
            used_gb  = mem.used  / (1024 ** 3)
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
            total_gb = disk.total / (1024 ** 3)
            used_gb  = disk.used  / (1024 ** 3)
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

    # ── 面向自动休眠逻辑的数值型方法 ──────────────────────────

    def get_cpu_percent(self) -> Optional[float]:
        """
        返回当前 CPU 使用率百分比（0~100 的浮点数）。
        psutil 未安装或查询异常时返回 None，调用方应按"不触发休眠"处理。
        interval=0 使用上次调用间隔，响应更快，适合高频 10s 轮询。
        """
        try:
            psutil = _require_psutil()
            # interval=None 不阻塞，使用自上次调用以来的平均值
            return psutil.cpu_percent(interval=None)
        except Exception as e:
            logger.debug(f"get_cpu_percent 异常（忽略）：{e}")
            return None

    def get_running_processes(self) -> list[str]:
        """
        返回当前所有运行进程的名称列表（小写）。
        psutil 未安装或查询异常时返回空列表，调用方应按"无黑名单进程"处理。
        """
        try:
            psutil = _require_psutil()
            names: list[str] = []
            for proc in psutil.process_iter(["name"]):
                try:
                    name = proc.info.get("name") or ""
                    if name:
                        names.append(name.lower())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # 进程在遍历过程中退出或无权限，正常忽略
                    pass
            return names
        except Exception as e:
            logger.debug(f"get_running_processes 异常（忽略）：{e}")
            return []
