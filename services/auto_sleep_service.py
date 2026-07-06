"""
自动休眠检测服务
每隔固定周期（由 main.py 中的 QTimer 驱动）检查系统资源状态，
根据配置决定是否自动将助手切换到 sleep 或 idle 状态。

检测规则（优先级从高到低）：
  1. sleep（高负载）：CPU 占用 > cpu_sleep_threshold
  2. sleep（黑名单进程）：blacklist_processes 中的进程正在运行
  3. idle（长时间无操作）：超过 idle_sleep_minutes 无用户交互
  4. 否则维持当前状态，不做切换

设计原则：
  - 不包含任何 UI 逻辑，只负责判断并调用 StateManager.set_state()
  - 所有 psutil 调用已在 MonitorService 内部异常捕获，不会向上抛出
  - sleep 触发时通过回调通知外部（如托盘弹窗），与 UI 解耦
  - 已处于 sleep 状态时不重复触发通知
"""

from typing import Callable, Optional, TYPE_CHECKING

from services.monitor_service import MonitorService
from app.logger import setup_logger

if TYPE_CHECKING:
    from app.config import BehaviorConfig
    from app.state_manager import StateManager

logger = setup_logger()


class AutoSleepService:
    """
    自动休眠检测服务。

    使用方式（在 main.py 中）：
        svc = AutoSleepService(
            state_manager=state_manager,
            config=app_config.behavior,
        )
        svc.set_sleep_notify_callback(tray.show_sleep_notification)

        _timer = QTimer()
        _timer.setInterval(10 * 1000)          # 每 10 秒检测一次
        _timer.timeout.connect(svc.check)
        _timer.start()
    """

    def __init__(
        self,
        state_manager: "StateManager",
        config: Optional["BehaviorConfig"] = None,
    ):
        self._state_manager = state_manager
        self._config        = config
        self._monitor       = MonitorService()
        # sleep 通知回调（仅在状态"首次进入 sleep"时触发）
        self._sleep_notify_cb: Optional[Callable[[], None]] = None

    # ── 公开接口 ─────────────────────────────────────────────

    def set_sleep_notify_callback(self, callback: Callable[[], None]):
        """
        注册 sleep 通知回调，进入 sleep 时调用一次。
        签名：callback() → None
        """
        self._sleep_notify_cb = callback

    def check(self):
        """
        执行一次资源检测，根据结果切换状态。
        由 QTimer.timeout 信号驱动，每 10 秒调用一次。
        """
        try:
            self._do_check()
        except Exception as e:
            # 检测本身出错不影响主程序运行
            logger.error(f"AutoSleepService.check 异常：{e}")

    # ── 私有逻辑 ──────────────────────────────────────────────

    def _do_check(self):
        """核心检测逻辑，抛出的异常由 check() 捕获"""
        cfg             = self._config
        current_state   = self._state_manager.get_state()

        # ── 从 config 读取阈值，未配置时用安全默认值 ───────────
        cpu_threshold      = getattr(cfg, "cpu_sleep_threshold", 80)    # CPU 阈值（%）
        idle_minutes       = getattr(cfg, "idle_sleep_minutes",  10)    # 空闲分钟数
        blacklist: list    = getattr(cfg, "blacklist_processes",  [])   # 黑名单进程列表

        # ── 规则1：CPU 超阈值 → sleep ──────────────────────────
        cpu = self._monitor.get_cpu_percent()
        if cpu is not None and cpu > cpu_threshold:
            reason = f"CPU 占用 {cpu:.0f}% 超过阈值 {cpu_threshold}%"
            self._trigger_sleep(reason)
            return

        # ── 规则2：黑名单进程运行 → sleep ──────────────────────
        if blacklist:
            running = self._monitor.get_running_processes()  # 全部小写
            for proc_name in blacklist:
                if proc_name.lower() in running:
                    reason = f"检测到黑名单进程：{proc_name}"
                    self._trigger_sleep(reason)
                    return

        # ── 若当前处于 sleep 且触发条件解除，切回 idle ──────────
        # （由用户主动操作触发 active；此处仅在条件解除时退出 sleep）
        if current_state == "sleep":
            logger.debug("AutoSleepService：sleep 触发条件已解除，切回 idle")
            self._state_manager.set_state("idle")
            return

        # ── 规则3：长时间无操作 → idle ─────────────────────────
        # 仅当前状态为 active 时才降级到 idle（不覆盖手动 sleep）
        if current_state == "active":
            if self._state_manager.is_idle_timeout(idle_minutes):
                logger.info(
                    f"超过 {idle_minutes} 分钟无交互，自动进入 idle"
                )
                self._state_manager.set_state("idle")

    def _trigger_sleep(self, reason: str):
        """
        触发 sleep 状态切换，并在"首次"进入时触发通知回调。
        重复触发（原因相同）时不重复弹窗。
        """
        changed = self._state_manager.set_state("sleep")

        if changed:
            logger.info(f"自动进入 sleep：{reason}")
            if self._sleep_notify_cb:
                try:
                    self._sleep_notify_cb()
                except Exception as e:
                    logger.error(f"sleep 通知回调异常：{e}")
        else:
            # 已处于 sleep，不重复通知
            logger.debug(f"保持 sleep（{reason}）")
