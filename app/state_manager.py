"""
助手运行状态管理模块
统一维护助手的当前状态，所有状态变化都经由本模块，
各 UI 组件通过注册回调感知状态，不直接相互调用。

状态说明：
    active  正常工作（有交互、有对话）
    idle    省电待机（一段时间无操作后自动进入，或由外部触发）
    sleep   休眠（CPU 超阈值 / 黑名单进程运行 / 用户主动触发，宠物切换为 sleep 图）
"""

import time
from typing import Callable
from app.logger import setup_logger

logger = setup_logger()

# 合法状态集合
VALID_STATES = {"active", "idle", "sleep"}

# 助手状态 → 宠物显示状态的映射
# active/idle 都显示 idle 图，sleep 显示 sleep 图
_STATE_TO_PET: dict[str, str] = {
    "active": "idle",
    "idle":   "idle",
    "sleep":  "sleep",
}


class StateManager:
    """
    助手运行状态的单一数据源。

    其他模块不应自行保存"当前状态"，统一通过本类读写。

    使用方式：
        sm = StateManager()
        sm.add_listener(my_callback)       # 注册状态变化监听
        sm.set_state("sleep")              # 变更状态
        print(sm.get_state())              # 读取当前状态
        sm.touch_interaction()             # 用户有操作时调用，更新交互时间
        sm.is_idle_timeout(minutes=10)     # 判断是否超过空闲阈值
    """

    def __init__(self, initial_state: str = "idle"):
        if initial_state not in VALID_STATES:
            raise ValueError(f"非法初始状态：{initial_state!r}，合法值：{VALID_STATES}")
        self._state: str = initial_state
        self._listeners: list[Callable[[str, str], None]] = []
        # 记录最后一次用户交互的时间戳（Unix time，秒）
        self._last_interaction_time: float = time.time()

    # ── 公开接口 ─────────────────────────────────────────────

    def get_state(self) -> str:
        """返回当前状态字符串"""
        return self._state

    def set_state(self, new_state: str) -> bool:
        """
        切换到指定状态。
        若状态未改变，静默忽略（不触发回调）。
        返回 True 表示状态发生了变化。
        """
        if new_state not in VALID_STATES:
            logger.warning(f"StateManager: 非法状态 {new_state!r}，忽略")
            return False

        if new_state == self._state:
            return False

        old_state = self._state
        self._state = new_state
        logger.debug(f"状态切换：{old_state} → {new_state}")
        self._notify(old_state, new_state)
        return True

    def add_listener(self, callback: Callable[[str, str], None]):
        """
        注册状态变化监听器。
        callback 签名：callback(old_state: str, new_state: str)
        """
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, str], None]):
        """移除已注册的监听器"""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def get_pet_state(self) -> str:
        """
        返回当前助手状态对应的宠物显示状态。
        供 FloatingPetWindow 使用，屏蔽内部状态细节。
        """
        return _STATE_TO_PET.get(self._state, "idle")

    # ── 交互时间管理 ──────────────────────────────────────────

    def touch_interaction(self):
        """
        记录用户交互发生的时间（点击宠物、打开聊天窗口、发送消息等均应调用）。
        同时将状态从 idle/sleep 恢复到 active。
        """
        self._last_interaction_time = time.time()
        # 有交互时自动恢复到 active（sleep/idle → active）
        if self._state in ("idle", "sleep"):
            self.set_state("active")

    def get_last_interaction_time(self) -> float:
        """返回最后一次交互的时间戳（Unix time，秒）"""
        return self._last_interaction_time

    def is_idle_timeout(self, minutes: int) -> bool:
        """
        判断距上次交互是否已超过指定分钟数。
        AutoSleepService 用此方法判断是否应进入 idle。
        minutes <= 0 时始终返回 False（禁用空闲自动休眠）。
        """
        if minutes <= 0:
            return False
        elapsed_seconds = time.time() - self._last_interaction_time
        return elapsed_seconds >= minutes * 60

    # ── 内部方法 ──────────────────────────────────────────────

    def _notify(self, old_state: str, new_state: str):
        """依次调用所有监听器，单个失败不影响其他"""
        for cb in list(self._listeners):
            try:
                cb(old_state, new_state)
            except Exception as e:
                logger.error(f"StateManager 监听器异常：{e}")
