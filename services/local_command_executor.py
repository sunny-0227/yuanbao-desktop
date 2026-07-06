"""
本地指令执行器
在后台 QThread 中执行本地指令（CommandDispatcher.handle），
通过 Qt 信号将结果异步返回给 UI，避免阻塞主线程。

设计要点：
- 持有 CommandDispatcher 引用，构造时完成所有 Service 初始化
- execute(text) 启动 QThread，执行完成后 emit result_ready 或 error_occurred
- 内置 AIService + CacheService：未命中本地规则时自动调用 AI，并读写缓存
- 通过 connect_ai_start 让 UI 感知当前请求类型
- 外部仍可通过 set_ai_handler() 注入自定义 AI 函数覆盖内置实现
- UI 层（ChatWindow）只需连接信号，不直接调用 Service
"""

from PySide6.QtCore import QThread, Signal

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
    执行完成后通过信号通知结果，线程用完即销毁。
    同时通过 is_ai_request 标志告诉 UI 本次是否走了 AI 流程。
    """
    result_ready   = Signal(str)   # 正常结果文本
    error_occurred = Signal(str)   # 执行异常文本
    ai_started     = Signal()      # 确认进入 AI 流程时触发（用于 UI 更新 loading 提示）

    def __init__(
        self,
        dispatcher: CommandDispatcher,
        text: str,
        ai_handler=None,
        parent=None,
    ):
        super().__init__(parent)
        self._dispatcher = dispatcher
        self._text       = text
        self._ai_handler = ai_handler   # 最终 AI 调用函数（已含缓存逻辑）

    def run(self):
        try:
            reply = self._dispatcher.handle(self._text)

            if reply:
                # 本地指令命中，直接返回执行结果
                self.result_ready.emit(reply)
            else:
                # 未命中本地规则 → AI 流程
                # 通知 UI 切换为 AI loading 状态（从后台线程 emit 是安全的）
                self.ai_started.emit()
                self.result_ready.emit(self._call_ai(self._text))

        except Exception as e:
            logger.error(f"指令执行线程异常：{e}")
            self.error_occurred.emit(f"⚠️ 执行出错：{e}")

    def _call_ai(self, text: str) -> str:
        """调用 AI handler（已在 LocalCommandExecutor 中封装缓存逻辑）"""
        if self._ai_handler:
            try:
                return self._ai_handler(text)
            except Exception as e:
                logger.error(f"AI handler 异常：{e}")
                return f"⚠️ AI 服务出错：{e}"
        # 兜底：Executor 总会设置 handler，不应到达此处
        return "当前未配置 AI 服务，请在 .env 中填写模型配置。"


class LocalCommandExecutor:
    """
    本地指令异步执行入口。

    ChatWindow 持有此对象，调用 execute() 后等待信号回调。
    每次 execute() 创建新线程，线程执行完毕后自动清理。

    内置 AI 调用流程（先查缓存，再请求，最后写缓存）：
        用户输入 → CommandDispatcher（本地规则）
                                    ↓ 未命中
                       CacheService.get_cached_answer()
                                    ↓ 未命中
                          AIService.ask_ai()
                                    ↓
                       CacheService.save_answer()
                                    ↓
                          返回给 ChatWindow

    信号说明：
        connect_result(cb)      → 收到最终回复时回调
        connect_error(cb)       → 执行出错时回调
        connect_ai_start(cb)    → 确认进入 AI 流程时回调（UI 可据此更新 loading 文案）

    使用方式：
        executor = LocalCommandExecutor(config=app_config)
        executor.connect_result(chat_window._on_reply)
        executor.connect_error(chat_window._on_error)
        executor.connect_ai_start(chat_window._on_ai_start)
        executor.execute("帮我写一封请假邮件")
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        todo_service: Optional[TodoService] = None,
    ):
        # 将外部注入的 TodoService 传给 Dispatcher，保证全局唯一实例
        self._dispatcher = CommandDispatcher(config=config, todo_service=todo_service)

        # 内置 AI 服务（httpx 实现，兼容 OpenAI 接口）
        ai_cfg = config.ai if config else None
        self._ai_svc = AIService(config=ai_cfg)

        # 内置缓存服务（enable_ai_cache 来自 config）
        cache_enabled = config.ai.enable_ai_cache if (config and config.ai) else True
        self._cache_svc = CacheService(enable=cache_enabled)

        # 构建内置 AI handler（含缓存逻辑），外部可通过 set_ai_handler 覆盖
        self._ai_handler = self._make_ai_handler()

        self._thread: Optional[_ExecuteThread] = None
        # 用 list 存回调，手动实现 signal-like 行为
        # （LocalCommandExecutor 不继承 QObject，无法直接声明 Signal）
        self._result_cbs:   list = []
        self._error_cbs:    list = []
        self._ai_start_cbs: list = []   # AI 流程开始时的回调

    # ── 公开接口 ──────────────────────────────────────────────

    def connect_result(self, callback):
        """注册结果回调，签名：callback(reply: str)"""
        if callback not in self._result_cbs:
            self._result_cbs.append(callback)

    def connect_error(self, callback):
        """注册错误回调，签名：callback(error_msg: str)"""
        if callback not in self._error_cbs:
            self._error_cbs.append(callback)

    def connect_ai_start(self, callback):
        """
        注册"AI 流程开始"回调，无参数。
        在确认本次请求需要调用 AI（本地规则未命中）后触发，
        供 ChatWindow 把 loading 文案从"执行中…"更新为"思考中…"。
        """
        if callback not in self._ai_start_cbs:
            self._ai_start_cbs.append(callback)

    def set_ai_handler(self, handler):
        """
        注入自定义 AI 调用函数，签名：handler(text: str) -> str。
        覆盖内置的 AIService + CacheService 逻辑。
        """
        self._ai_handler = handler

    @property
    def ai_configured(self) -> bool:
        """返回 AI 是否已配置（用于 ChatWindow 显示欢迎提示）"""
        return self._ai_svc.is_configured()

    def execute(self, text: str) -> None:
        """
        在后台线程中执行指令，结果通过回调通知。
        若上一个线程还在运行，等待其完成后再启动（防止并发冲突）。
        """
        # 等待上一个线程完成（最多等 5 秒，超时强制终止）
        if self._thread and self._thread.isRunning():
            if not self._thread.wait(5000):
                logger.warning("上一个指令线程超时，强制终止")
                self._thread.terminate()

        thread = _ExecuteThread(self._dispatcher, text, self._ai_handler)
        thread.result_ready.connect(self._on_result)
        thread.error_occurred.connect(self._on_error)
        thread.ai_started.connect(self._on_ai_started)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    # ── 私有方法 ──────────────────────────────────────────────

    def _make_ai_handler(self):
        """
        构建含缓存逻辑的 AI handler 闭包：
          1. 先查缓存
          2. 缓存未命中则调用 AIService.ask_ai()
          3. 将有效回答写入缓存（错误提示不缓存）
        """
        ai_svc    = self._ai_svc
        cache_svc = self._cache_svc

        def _handler(text: str) -> str:
            # 步骤一：查缓存
            cached = cache_svc.get_cached_answer(text)
            if cached:
                logger.debug("使用缓存回复")
                return cached

            # 步骤二：调用 AI（所有异常在 ask_ai 内部捕获，不会抛出）
            answer = ai_svc.ask_ai(text)

            # 步骤三：仅当回答有效时才写缓存（错误提示不缓存）
            if answer and not answer.startswith("⚠️") and not answer.startswith("当前未配置"):
                cache_svc.save_answer(text, answer)

            return answer

        return _handler

    def _on_result(self, reply: str):
        """线程 result_ready 信号 → 转发给所有注册回调"""
        for cb in list(self._result_cbs):
            try:
                cb(reply)
            except Exception as e:
                logger.error(f"result 回调异常：{e}")

    def _on_error(self, msg: str):
        """线程 error_occurred 信号 → 转发给所有注册回调"""
        for cb in list(self._error_cbs):
            try:
                cb(msg)
            except Exception as e:
                logger.error(f"error 回调异常：{e}")

    def _on_ai_started(self):
        """线程 ai_started 信号 → 通知 UI 进入 AI 等待状态"""
        for cb in list(self._ai_start_cbs):
            try:
                cb()
            except Exception as e:
                logger.error(f"ai_start 回调异常：{e}")
