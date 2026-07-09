"""
本地指令执行器（含任务取消支持）

线程安全设计：
- _ExecuteThread 完成后先触发 _on_thread_finished 将 Python 引用置 None，
  再由 Qt 调用 deleteLater 析构 C++ 对象，避免 RuntimeError。
- _is_thread_running() 用 try/except RuntimeError 防崩溃。
- execute() 携带 task_id，所有回调均透传 task_id，
  ChatWindow 据此过滤"已被取消的旧任务"的结果。
- cancel_current_task() 通过 requestInterruption() 通知线程尽量提前退出，
  并设置 cancel flag；即使线程无法立即中断（如 AI 请求），
  旧 task_id 的结果回调也会被 ChatWindow 丢弃。
"""

from PySide6.QtCore import QThread, Signal, QObject

from services.command_dispatcher import CommandDispatcher
from services.todo_service import TodoService
from services.ai_service import AIService
from services.cache_service import CacheService
from app.config import AppConfig
from app.logger import setup_logger
from typing import Optional

logger = setup_logger()


class _ExecuteThread(QThread):
    """
    单次指令执行线程。
    携带 task_id，所有信号均透传 task_id，供 ChatWindow 过滤旧任务结果。
    """
    # (task_id, reply)
    result_ready   = Signal(str, str)
    # (task_id, error_msg)
    error_occurred = Signal(str, str)
    # (task_id)
    ai_started     = Signal(str)

    def __init__(
        self,
        dispatcher: CommandDispatcher,
        text: str,
        task_id: str,
        ai_handler=None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._dispatcher = dispatcher
        self._text       = text
        self._task_id    = task_id
        self._ai_handler = ai_handler

    def run(self):
        try:
            # 执行前检查是否已被取消
            if self.isInterruptionRequested():
                return

            reply = self._dispatcher.handle(self._text)

            if self.isInterruptionRequested():
                return

            if reply:
                # 本地指令命中，直接返回
                self.result_ready.emit(self._task_id, reply)
            else:
                # 未命中本地规则 → AI 流程
                self.ai_started.emit(self._task_id)

                if self.isInterruptionRequested():
                    return

                self.result_ready.emit(self._task_id, self._call_ai(self._text))

        except Exception as e:
            logger.error(f"指令执行线程异常：{e}")
            if not self.isInterruptionRequested():
                self.error_occurred.emit(self._task_id, f"⚠️ 执行出错：{e}")

    def _call_ai(self, text: str) -> str:
        """调用 AI handler（含缓存逻辑）"""
        if self._ai_handler:
            try:
                return self._ai_handler(text)
            except Exception as e:
                logger.error(f"AI handler 异常：{e}")
                return f"⚠️ AI 服务出错：{e}"
        return "当前未配置 AI 服务，请在 .env 中填写模型配置。"


class LocalCommandExecutor:
    """
    本地指令异步执行入口。

    核心机制：
        execute(text, task_id)   — 创建线程执行指令，携带 task_id
        cancel_current_task()    — 取消当前任务（逻辑取消 + 尽量中断线程）

    回调签名均带 task_id，ChatWindow 可据此过滤已取消任务的旧结果：
        on_result(task_id, reply)
        on_error(task_id, error_msg)
        on_ai_start(task_id)
        on_finished(task_id)      — 线程结束时触发（无论成功/失败/取消）
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        todo_service: Optional[TodoService] = None,
    ):
        self._dispatcher = CommandDispatcher(config=config, todo_service=todo_service)

        ai_cfg = config.ai if config else None
        self._ai_svc = AIService(config=ai_cfg)

        cache_enabled = config.ai.enable_ai_cache if (config and config.ai) else True
        self._cache_svc = CacheService(enable=cache_enabled)

        self._ai_handler = self._make_ai_handler()

        # 当前线程引用，None 表示空闲
        self._thread: Optional[_ExecuteThread] = None

        # 各类型回调列表
        self._result_cbs:   list = []
        self._error_cbs:    list = []
        self._ai_start_cbs: list = []
        self._finished_cbs: list = []

    # ── 公开接口 ──────────────────────────────────────────────

    def connect_result(self, callback):
        """注册结果回调，签名：callback(task_id: str, reply: str)"""
        if callback not in self._result_cbs:
            self._result_cbs.append(callback)

    def connect_error(self, callback):
        """注册错误回调，签名：callback(task_id: str, error_msg: str)"""
        if callback not in self._error_cbs:
            self._error_cbs.append(callback)

    def connect_ai_start(self, callback):
        """注册 AI 开始回调，签名：callback(task_id: str)"""
        if callback not in self._ai_start_cbs:
            self._ai_start_cbs.append(callback)

    def connect_finished(self, callback):
        """注册线程结束回调，签名：callback(task_id: str)"""
        if callback not in self._finished_cbs:
            self._finished_cbs.append(callback)

    def set_ai_handler(self, handler):
        """注入自定义 AI 函数，签名：handler(text: str) -> str"""
        self._ai_handler = handler

    @property
    def ai_configured(self) -> bool:
        return self._ai_svc.is_configured()

    def execute(self, text: str, task_id: str) -> None:
        """
        在后台线程中执行指令。
        若上一个线程仍在运行，直接返回忙碌提示，不创建新线程。
        调用方（ChatWindow）应在调用前先调用 cancel_current_task()。
        """
        if self._is_thread_running():
            logger.warning("上一个指令线程仍在运行，拒绝重复提交")
            self._on_result(task_id, "当前任务正在执行，请先点击「停止」。")
            return

        thread = _ExecuteThread(
            self._dispatcher, text, task_id, self._ai_handler
        )

        # 信号按顺序连接：Python 侧清理在 deleteLater 之前
        thread.result_ready.connect(self._on_result)
        thread.error_occurred.connect(self._on_error)
        thread.ai_started.connect(self._on_ai_started)
        thread.finished.connect(lambda: self._on_thread_finished(task_id))
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        thread.start()
        logger.debug(f"线程已启动，task_id={task_id}")

    def cancel_current_task(self) -> bool:
        """
        取消当前任务。
        - 通过 requestInterruption() 通知线程尽量提前退出
        - 对于 AI 同步请求无法真正中断，但 ChatWindow 侧通过 task_id 过滤旧结果

        返回 True 表示确实有任务在运行并已发出取消请求。
        """
        if not self._is_thread_running():
            return False
        try:
            self._thread.requestInterruption()
            logger.info("已发送线程中断请求")
        except RuntimeError:
            self._thread = None
        return True

    # ── 私有方法 ──────────────────────────────────────────────

    def _is_thread_running(self) -> bool:
        """安全判断线程是否仍在运行，捕获 C++ 对象已删除异常"""
        if self._thread is None:
            return False
        try:
            return self._thread.isRunning()
        except RuntimeError:
            logger.debug("_ExecuteThread C++ 对象已删除，清理引用")
            self._thread = None
            return False

    def _on_thread_finished(self, task_id: str):
        """
        线程结束时：先置 None（必须在 deleteLater 前执行），
        再通知外部 finished 回调。
        """
        self._thread = None
        logger.debug(f"线程已结束，task_id={task_id}")
        for cb in list(self._finished_cbs):
            try:
                cb(task_id)
            except Exception as e:
                logger.error(f"finished 回调异常：{e}")

    def _make_ai_handler(self):
        """构建含缓存逻辑的 AI handler 闭包"""
        ai_svc    = self._ai_svc
        cache_svc = self._cache_svc

        def _handler(text: str) -> str:
            cached = cache_svc.get_cached_answer(text)
            if cached:
                logger.debug("使用缓存回复")
                return cached
            answer = ai_svc.ask_ai(text)
            if answer and not answer.startswith("⚠️") and not answer.startswith("当前未配置"):
                cache_svc.save_answer(text, answer)
            return answer

        return _handler

    def _on_result(self, task_id: str, reply: str):
        for cb in list(self._result_cbs):
            try:
                cb(task_id, reply)
            except Exception as e:
                logger.error(f"result 回调异常：{e}")

    def _on_error(self, task_id: str, msg: str):
        for cb in list(self._error_cbs):
            try:
                cb(task_id, msg)
            except Exception as e:
                logger.error(f"error 回调异常：{e}")

    def _on_ai_started(self, task_id: str):
        for cb in list(self._ai_start_cbs):
            try:
                cb(task_id)
            except Exception as e:
                logger.error(f"ai_start 回调异常：{e}")
