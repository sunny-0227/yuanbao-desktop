"""
配置加载模块
负责读取 config.json，并提供类型安全的配置对象。
新增字段时：在对应 dataclass 中添加属性，并在 load_config 中补充读取逻辑。
"""

import json
import os
from dataclasses import dataclass, field


# ── 子配置 dataclass ──────────────────────────────────────────

@dataclass
class AIConfig:
    """AI 服务配置"""
    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 1024
    system_prompt: str = (
        "你是一个专注于日常办公、学习和资料处理的桌面AI效率助手，"
        "名叫图图助手。请用简洁自然的中文回答问题，优先给出可操作的建议。"
    )
    enable_ai_cache: bool = True      # 是否启用 AI 回复本地缓存（预留）


@dataclass
class UIConfig:
    """界面配置"""
    theme: str = "dark"               # dark / light
    font_size: int = 14
    window_width: int = 420
    window_height: int = 680
    always_on_top: bool = False


@dataclass
class BehaviorConfig:
    """助手行为配置"""
    idle_sleep_minutes: int = 10          # 多少分钟无操作后进入 idle
    cpu_sleep_threshold: int = 80         # CPU 占用超过此值时不自动休眠（%）
    blacklist_processes: list = field(    # 这些进程运行时进入 sleep（用于游戏/全屏应用场景）
        default_factory=lambda: []        # 默认为空，避免误触发（explorer.exe 等系统进程始终运行）
    )


@dataclass
class SearchConfig:
    """搜索引擎配置"""
    engine: str = "bing"              # 默认搜索引擎 key
    engines: dict = field(default_factory=lambda: {
        "bing":   "https://www.bing.com/search?q=",
        "baidu":  "https://www.baidu.com/s?wd=",
        "google": "https://www.google.com/search?q=",
    })

    def get_search_url(self, query: str) -> str:
        """拼接搜索 URL，未知引擎自动降级到 bing"""
        base = self.engines.get(self.engine, self.engines["bing"])
        return base + query


@dataclass
class ScreenshotConfig:
    """截图配置"""
    save_dir: str = ""             # 为空时由 resolved_save_dir() 返回跨平台默认路径
    format: str = "png"
    auto_open: bool = False           # 截图后是否自动用图片查看器打开

    def resolved_save_dir(self) -> str:
        """返回实际保存目录：优先使用 save_dir 配置（支持 Windows 环境变量展开），
        未配置时返回跨平台用户图片目录。"""
        from pathlib import Path
        if self.save_dir:
            return os.path.expandvars(self.save_dir)
        # 跨平台默认路径
        return str(Path.home() / "Pictures" / "TutuAssistantScreenshots")


@dataclass
class VoiceConfig:
    """语音交互配置"""
    voice_enabled:       bool  = True                     # 是否启用语音功能（录音入口）
    asr_provider:        str   = "none"                   # none / whisper / online
    tts_enabled:         bool  = True                     # 是否启用回复语音播报
    tts_provider:        str   = "edge"                   # edge / system
    tts_voice:           str   = "zh-CN-XiaoxiaoNeural"   # edge-tts 音色
    tts_max_chars:       int   = 200                      # 最大播报字数
    pause_mic_during_tts: bool = True                     # 播报期间禁止录音（防自激）
    mute_when_recording:  bool = False                    # 录音时静音输出（第一阶段不用）


@dataclass
class AppConfig:
    """顶层应用配置，聚合所有子配置"""
    app_name: str = "轻量化桌面AI效率助手"
    pet_name: str = "图图助手"
    log_level: str = "INFO"
    ai: AIConfig = field(default_factory=AIConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    screenshot: ScreenshotConfig = field(default_factory=ScreenshotConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    # 快捷应用列表，每项为 {"name": str, "command": str, "comment": str}
    quick_apps: list = field(default_factory=list)
    # 快捷文件夹列表，每项为 {"name": str, "path": str}
    quick_folders: list = field(default_factory=list)


# ── 加载函数 ──────────────────────────────────────────────────

def load_config(config_path: str) -> AppConfig:
    """
    从 config.json 加载配置，并用环境变量覆盖敏感字段。
    文件不存在或解析失败时使用 dataclass 默认值，不崩溃。
    兼容旧版 config.json（缺少新字段时自动使用默认值）。
    """
    config = AppConfig()

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            # ── 顶层字段 ────────────────────────────────────
            config.app_name  = raw.get("app_name",  config.app_name)
            config.pet_name  = raw.get("pet_name",  config.pet_name)
            config.log_level = raw.get("log_level", config.log_level)

            # ── AI 配置 ─────────────────────────────────────
            ai = raw.get("ai", {})
            config.ai = AIConfig(
                provider=ai.get("provider",         config.ai.provider),
                api_key=ai.get("api_key",           config.ai.api_key),
                base_url=ai.get("base_url",         config.ai.base_url),
                model=ai.get("model",               config.ai.model),
                temperature=ai.get("temperature",   config.ai.temperature),
                max_tokens=ai.get("max_tokens",     config.ai.max_tokens),
                system_prompt=ai.get("system_prompt", config.ai.system_prompt),
                enable_ai_cache=ai.get("enable_ai_cache", config.ai.enable_ai_cache),
            )

            # ── UI 配置 ─────────────────────────────────────
            ui = raw.get("ui", {})
            config.ui = UIConfig(
                theme=ui.get("theme",               config.ui.theme),
                font_size=ui.get("font_size",       config.ui.font_size),
                window_width=ui.get("window_width", config.ui.window_width),
                window_height=ui.get("window_height", config.ui.window_height),
                always_on_top=ui.get("always_on_top", config.ui.always_on_top),
            )

            # ── 行为配置 ─────────────────────────────────────
            beh = raw.get("behavior", {})
            config.behavior = BehaviorConfig(
                idle_sleep_minutes=beh.get("idle_sleep_minutes",
                                           config.behavior.idle_sleep_minutes),
                cpu_sleep_threshold=beh.get("cpu_sleep_threshold",
                                            config.behavior.cpu_sleep_threshold),
                blacklist_processes=beh.get("blacklist_processes",
                                            config.behavior.blacklist_processes),
            )

            # ── 搜索配置 ─────────────────────────────────────
            sch = raw.get("search", {})
            config.search = SearchConfig(
                engine=sch.get("engine",   config.search.engine),
                engines=sch.get("engines", config.search.engines),
            )

            # ── 截图配置 ─────────────────────────────────────
            ss = raw.get("screenshot", {})
            config.screenshot = ScreenshotConfig(
                save_dir=ss.get("save_dir",     config.screenshot.save_dir),
                format=ss.get("format",         config.screenshot.format),
                auto_open=ss.get("auto_open",   config.screenshot.auto_open),
            )

            # ── 语音配置 ─────────────────────────────────────
            vc = raw  # 语音字段放在顶层
            config.voice = VoiceConfig(
                voice_enabled=vc.get("voice_enabled",       config.voice.voice_enabled),
                asr_provider=vc.get("asr_provider",         config.voice.asr_provider),
                tts_enabled=vc.get("tts_enabled",           config.voice.tts_enabled),
                tts_provider=vc.get("tts_provider",         config.voice.tts_provider),
                tts_voice=vc.get("tts_voice",               config.voice.tts_voice),
                tts_max_chars=vc.get("tts_max_chars",       config.voice.tts_max_chars),
                pause_mic_during_tts=vc.get("pause_mic_during_tts", config.voice.pause_mic_during_tts),
                mute_when_recording=vc.get("mute_when_recording",   config.voice.mute_when_recording),
            )

            # ── 快捷应用 / 文件夹 ────────────────────────────
            config.quick_apps    = raw.get("quick_apps",    config.quick_apps)
            config.quick_folders = raw.get("quick_folders", config.quick_folders)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # config.json 损坏时备份为 .bak，并继续使用 dataclass 默认值
            try:
                import shutil
                shutil.copy2(config_path, config_path + ".bak")
            except Exception:
                pass
            import logging
            logging.getLogger(__name__).error(
                f"[配置] 读取 config.json 失败，已备份为 .bak，使用默认配置：{e}"
            )

    # ── 环境变量覆盖（优先级最高，保护敏感信息）────────────────
    if os.getenv("AI_API_KEY"):
        config.ai.api_key = os.environ["AI_API_KEY"]

    if os.getenv("AI_BASE_URL"):
        config.ai.base_url = os.environ["AI_BASE_URL"]

    # 兼容 AI_API_BASE_URL（与 ai_service.py 保持一致）
    if os.getenv("AI_API_BASE_URL"):
        config.ai.base_url = os.environ["AI_API_BASE_URL"]

    if os.getenv("AI_MODEL"):
        config.ai.model = os.environ["AI_MODEL"]

    # 兼容 AI_MODEL_NAME（与 ai_service.py 保持一致）
    if os.getenv("AI_MODEL_NAME"):
        config.ai.model = os.environ["AI_MODEL_NAME"]

    return config
