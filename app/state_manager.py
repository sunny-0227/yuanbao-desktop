"""功耗状态与工作状态分开；手动休眠在用户恢复前保持。"""

import time
from typing import Callable

VALID_STATES = {"active", "idle", "sleep"}


class StateManager:
    def __init__(self, initial_state="active"):
        self._state = initial_state
        self._manual_sleep = False
        self.reason = ""
        self._listeners: list[Callable] = []
        self._last_interaction_time = time.monotonic()

    def get_state(self):
        return self._state

    @property
    def manual_sleep(self):
        return self._manual_sleep

    def set_state(self, new_state, *, manual=False, reason=""):
        if new_state not in VALID_STATES:
            raise ValueError("无效状态")
        if manual:
            self._manual_sleep = new_state == "sleep"
        if self._manual_sleep and new_state != "sleep":
            return False
        self.reason = reason
        if self._state == new_state:
            return False
        old, self._state = self._state, new_state
        for callback in tuple(self._listeners):
            callback(old, new_state)
        return True

    def add_listener(self, callback):
        if callback not in self._listeners:
            self._listeners.append(callback)

    def touch_interaction(self):
        self._last_interaction_time = time.monotonic()
        self._manual_sleep = False
        self.set_state("active")

    def is_idle_timeout(self, minutes):
        return minutes > 0 and time.monotonic() - self._last_interaction_time >= minutes * 60

    def get_pet_state(self):
        return "sleep" if self._state == "sleep" else "idle"
