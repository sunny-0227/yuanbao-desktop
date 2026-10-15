"""非阻塞资源采样、连续高负载判断与恢复迟滞。"""

import ctypes
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal, Slot


def snapshot():
    import psutil

    from app.utils import is_windows

    result = {
        "cpu": psutil.cpu_percent(interval=0.1),
        "processes": [],
        "foreground": "",
        "system_idle": None,
    }
    result["processes"] = [
        p.info["name"].lower() for p in psutil.process_iter(["name"]) if p.info["name"]
    ]
    if is_windows():

        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LastInput(ctypes.sizeof(LastInput), 0)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            ticks = ctypes.windll.kernel32.GetTickCount()
            result["system_idle"] = ((ticks - info.dwTime) & 0xFFFFFFFF) / 1000
        from app.windows import user32_api

        user32 = user32_api()
        pid = ctypes.c_ulong()
        hwnd = user32.GetForegroundWindow()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            result["foreground"] = psutil.Process(pid.value).name().lower()
        except psutil.Error:
            pass
    return result


class AutoSleepService(QObject):
    sampled = Signal(object)
    error = Signal(str)

    def __init__(self, state_manager, config, parent=None):
        super().__init__(parent)
        self.state_manager, self.config = state_manager, config
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="YuanbaoMonitor")
        self.busy = False
        self.high_samples = 0
        self.last_cpu = 0
        self.recovery_samples = 0
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setInterval(10000)
        self.timer.timeout.connect(self.check)
        self.sampled.connect(self.evaluate)
        self.timer.start()

    def check(self):
        if (
            self.busy
            or self.closed
            or not self.config.auto_sleep_enabled
            or self.state_manager.manual_sleep
        ):
            return
        self.busy = True

        def work():
            try:
                self.sampled.emit(snapshot())
            except Exception as exc:
                self.sampled.emit({"error": str(exc)})

        self.pool.submit(work)

    @Slot(object)
    def evaluate(self, value):
        self.busy = False
        if self.closed or not self.config.auto_sleep_enabled or self.state_manager.manual_sleep:
            return
        if "error" in value:
            self.error.emit(value["error"])
            return
        self.last_cpu = value["cpu"]
        threshold = self.config.cpu_sleep_threshold
        running = set(value["processes"])
        white = {p.lower() for p in self.config.whitelist_processes}
        black = {p.lower() for p in self.config.blacklist_processes} - white
        hit = bool(black & running)
        self.high_samples = self.high_samples + 1 if value["cpu"] > threshold else 0
        if hit or self.high_samples >= 2:
            self.state_manager.set_state(
                "sleep", reason="检测到黑名单软件" if hit else "持续高负载"
            )
            self.recovery_samples = 0
        elif self.state_manager.get_state() == "sleep":
            self.recovery_samples = (
                self.recovery_samples + 1 if value["cpu"] < threshold - 10 and not hit else 0
            )
            if self.recovery_samples >= 2:
                self.state_manager.set_state("idle", reason="系统负载已恢复")
        else:
            minutes = self.config.idle_sleep_minutes
            idle = self.state_manager.is_idle_timeout(minutes)
            if value["system_idle"] is not None and minutes > 0:
                idle = idle and value["system_idle"] >= minutes * 60
            if idle:
                self.state_manager.set_state("idle", reason="长时间无交互")
            elif (
                self.state_manager.get_state() == "idle"
                and value["system_idle"] is not None
                and value["system_idle"] < 2
            ):
                self.state_manager.touch_interaction()
        # 休眠仍保留低频守护检测，否则无法自动恢复。
        self.timer.setInterval(30000 if self.state_manager.get_state() == "sleep" else 10000)

    def update_config(self, config):
        self.config = config
        if not config.auto_sleep_enabled and not self.state_manager.manual_sleep:
            self.state_manager.touch_interaction()

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        self.pool.shutdown(wait=True, cancel_futures=True)
