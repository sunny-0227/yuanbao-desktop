"""统一后台任务队列；所有跨线程通知只走 Qt 信号。"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot


class LocalCommandExecutor(QObject):
    result = Signal(str, object)
    error = Signal(str, str)
    chunk = Signal(str, str)
    status = Signal(str, str)
    finished = Signal(str)
    _settled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="YuanbaoTasks")
        self.jobs = {}
        self.closed = False
        self._settled.connect(self._cleanup)

    def submit(self, function):
        if self.closed:
            raise RuntimeError("应用正在退出")
        if len(self.jobs) >= 32:
            raise RuntimeError("待处理操作较多，请稍后重试")
        ident, token = uuid.uuid4().hex, Event()
        self.jobs[ident] = token

        def run():
            initialized = False
            try:
                # Windows COM 必须在实际调用它的工作线程初始化。
                try:
                    import pythoncom

                    pythoncom.CoInitialize()
                    initialized = True
                except ImportError:
                    pass
                if token.is_set():
                    return
                value = function(
                    token,
                    lambda part: self.chunk.emit(ident, part),
                    lambda message: self.status.emit(ident, message),
                )
                if not token.is_set():
                    self.result.emit(ident, value)
            except Exception as exc:
                if not token.is_set():
                    self.error.emit(ident, str(exc))
            finally:
                if initialized:
                    pythoncom.CoUninitialize()
                self._settled.emit(ident)

        self.pool.submit(run)
        return ident

    @Slot(str)
    def _cleanup(self, ident):
        self.jobs.pop(ident, None)
        self.finished.emit(ident)

    def cancel(self, ident):
        if ident in self.jobs:
            self.jobs[ident].set()

    def shutdown(self):
        self.closed = True
        for token in self.jobs.values():
            token.set()
        # 正在执行的不可中断本地操作允许结束，不销毁仍运行的 QThread。
        self.pool.shutdown(wait=True, cancel_futures=True)
