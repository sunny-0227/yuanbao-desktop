"""
应用配置：字段声明、兼容解析、校验与用户目录持久化。
"""

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from urllib.parse import urlparse

from app.app_context import data_path, resource_path
from app.identity import APP_NAME, PET_NAME
from app.storage import atomic_json

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
        "名叫元宝，形象是一只长毛金虎斑猫。请用简洁自然的中文回答问题，优先给出可操作的建议。"
    )
    enable_ai_cache: bool = False  # 是否启用带有效期的请求缓存


@dataclass
class UIConfig:
    """界面配置"""

    theme: str = "light"  # dark / light
    font_size: int = 14
    window_width: int = 1000
    window_height: int = 740
    always_on_top: bool = False
    pet_size: int = 120
    pet_opacity: float = 0.95
    pet_skin: str = "default"
    pet_visible: bool = True
    pet_x: int = -1
    pet_y: int = -1
    edge_collapse: bool = True
    autostart: bool = False


@dataclass
class BehaviorConfig:
    """助手行为配置"""

    idle_sleep_minutes: int = 5  # 多少分钟无操作后进入 idle
    auto_sleep_enabled: bool = True
    whitelist_processes: list = field(default_factory=list)
    cpu_sleep_threshold: int = 80  # CPU 连续超过此值时自动休眠（%）
    blacklist_processes: list = field(  # 这些进程运行时进入 sleep（用于游戏/全屏应用场景）
        default_factory=lambda: []  # 默认为空，避免误触发（explorer.exe 等系统进程始终运行）
    )


@dataclass
class SearchConfig:
    """搜索引擎配置"""

    engine: str = "bing"  # 默认搜索引擎 key
    engines: dict = field(
        default_factory=lambda: {
            "bing": "https://www.bing.com/search?q=",
            "baidu": "https://www.baidu.com/s?wd=",
            "google": "https://www.google.com/search?q=",
        }
    )


@dataclass
class ScreenshotConfig:
    """截图配置"""

    save_dir: str = ""  # 为空时由 resolved_save_dir() 返回跨平台默认路径
    format: str = "png"
    auto_open: bool = False  # 截图后是否自动用图片查看器打开

    def resolved_save_dir(self) -> str:
        """返回实际保存目录：优先使用 save_dir 配置（支持 Windows 环境变量展开），
        未配置时返回跨平台用户图片目录。"""
        from pathlib import Path

        if self.save_dir:
            return os.path.expanduser(os.path.expandvars(self.save_dir))
        # 跨平台默认路径
        return str(Path.home() / "Pictures" / "YuanbaoScreenshots")


@dataclass
class VoiceConfig:
    """语音交互配置"""

    input_device: str = ""
    wake_enabled: bool = False
    wake_word: str = "元宝元宝"
    wake_model_path: str = ""
    asr_url: str = ""
    asr_key: str = ""
    asr_model: str = "whisper-1"
    offline_model: str = "tiny"
    voice_enabled: bool = True  # 是否启用语音功能（录音入口）
    asr_provider: str = "none"  # none / whisper / online
    tts_enabled: bool = True  # 是否启用回复语音播报
    tts_provider: str = "edge"  # edge / system
    tts_voice: str = "zh-CN-XiaoxiaoNeural"  # edge-tts 音色
    tts_max_chars: int = 200  # 最大播报字数


@dataclass
class AppConfig:
    """顶层应用配置，聚合所有子配置"""

    app_name: str = APP_NAME
    pet_name: str = PET_NAME
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
    ai_endpoints: list = field(default_factory=list)
    offline_ai_url: str = ""
    offline_ai_model: str = ""


# ── 配置持久化与兼容迁移 ────────────────────────────────────


def _section(cls, raw):
    if not isinstance(raw, dict):
        raise ValueError(f"{cls.__name__} 必须是对象")
    defaults = cls()
    result = {}
    for item in fields(cls):
        if cls is AppConfig and item.name in (
            "ai",
            "ui",
            "behavior",
            "search",
            "screenshot",
            "voice",
        ):
            continue
        value = raw.get(item.name, getattr(defaults, item.name))
        default = getattr(defaults, item.name)
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, int):
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(default, float):
            valid = isinstance(value, (float, int)) and not isinstance(value, bool)
        else:
            valid = isinstance(value, type(default))
        if not valid:
            raise ValueError(f"{item.name} 类型错误")
        result[item.name] = value
    return cls(**result)


def config_from_dict(raw):
    if not isinstance(raw, dict):
        raise ValueError("配置根节点必须是对象")
    cfg = _section(
        AppConfig,
        {
            k: v
            for k, v in raw.items()
            if k not in ("ai", "ui", "behavior", "search", "screenshot", "voice")
        },
    )
    for name, cls in (
        ("ai", AIConfig),
        ("ui", UIConfig),
        ("behavior", BehaviorConfig),
        ("search", SearchConfig),
        ("screenshot", ScreenshotConfig),
    ):
        setattr(cfg, name, _section(cls, raw.get(name, {})))
    legacy_voice = {f.name: raw[f.name] for f in fields(VoiceConfig) if f.name in raw}
    cfg.voice = _section(VoiceConfig, {**legacy_voice, **raw.get("voice", {})})
    if cfg.app_name in ("轻量化桌面AI效率助手", "图图桌面助手", "TutuAssistant", "tutu"):
        cfg.app_name = APP_NAME
    if cfg.pet_name in ("图图", "图图助手", "tutu"):
        cfg.pet_name = PET_NAME
    if cfg.voice.wake_word == "图图图图":
        cfg.voice.wake_word = "元宝元宝"
    cfg.ai.system_prompt = cfg.ai.system_prompt.replace("图图助手", PET_NAME)
    # 旧版窄聊天窗迁移为工作台尺寸。
    cfg.ui.window_width = max(840, cfg.ui.window_width)
    cfg.ui.window_height = max(560, cfg.ui.window_height)
    validate_config(cfg)
    return cfg


def validate_config(cfg):
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]+", cfg.ui.pet_skin):
        raise ValueError("皮肤名称只能含英文字母、数字、下划线和连字符")
    if cfg.ui.theme not in ("light", "dark"):
        raise ValueError("主题必须为 light 或 dark")
    if (
        not 0 <= cfg.behavior.idle_sleep_minutes <= 1440
        or not 1 <= cfg.behavior.cpu_sleep_threshold <= 100
    ):
        raise ValueError("休眠阈值超出范围")
    if not 64 <= cfg.ui.pet_size <= 240 or not 0.2 <= cfg.ui.pet_opacity <= 1:
        raise ValueError("形象大小或透明度超出范围")
    if (
        not 10 <= cfg.ui.font_size <= 24
        or not 840 <= cfg.ui.window_width <= 2400
        or not 560 <= cfg.ui.window_height <= 1800
    ):
        raise ValueError("界面尺寸或字号超出范围")
    if cfg.voice.asr_provider not in ("none", "online", "whisper", "auto"):
        raise ValueError("无效语音识别方式")
    if cfg.voice.tts_provider not in ("edge", "system"):
        raise ValueError("无效播报方式")
    if cfg.voice.wake_enabled and (
        cfg.voice.asr_provider == "none" or not cfg.voice.wake_word.strip()
    ):
        raise ValueError("启用唤醒需要配置语音识别和唤醒词")
    if not 20 <= cfg.voice.tts_max_chars <= 2000:
        raise ValueError("播报长度超出范围")
    if cfg.ai.provider not in ("none", "direct", "openai", "freellmapi"):
        raise ValueError("无效 AI 连接方式")
    if not 0 <= cfg.ai.temperature <= 2 or not 1 <= cfg.ai.max_tokens <= 32768:
        raise ValueError("AI 参数超出范围")
    for endpoint in cfg.ai_endpoints:
        if (
            not isinstance(endpoint, dict)
            or not endpoint.get("base_url")
            or not endpoint.get("model")
        ):
            raise ValueError("备用接口必须填写地址与模型")
    for value in [
        cfg.ai.base_url,
        cfg.voice.asr_url,
        cfg.offline_ai_url,
        *(e.get("base_url", "") for e in cfg.ai_endpoints),
    ]:
        if value and (
            urlparse(value).scheme not in ("http", "https") or not urlparse(value).netloc
        ):
            raise ValueError("接口地址必须是有效 HTTP/HTTPS 地址")
    for entries in (cfg.quick_apps, cfg.quick_folders):
        if any(not isinstance(e, dict) or not e.get("name", "").strip() for e in entries):
            raise ValueError("快捷入口必须填写名称")
    for names in (cfg.behavior.blacklist_processes, cfg.behavior.whitelist_processes):
        if any(not isinstance(name, str) for name in names):
            raise ValueError("进程名单必须是文本列表")


def apply_environment(cfg):
    cfg.ai.api_key = os.getenv("AI_API_KEY") or cfg.ai.api_key
    cfg.ai.base_url = os.getenv("AI_API_BASE_URL") or os.getenv("AI_BASE_URL") or cfg.ai.base_url
    cfg.ai.model = os.getenv("AI_MODEL_NAME") or os.getenv("AI_MODEL") or cfg.ai.model
    cfg.voice.asr_key = os.getenv("ASR_API_KEY") or cfg.voice.asr_key
    return cfg


class ConfigStore:
    def __init__(self, path=None):
        self.path = Path(path or data_path("config.json"))

    def load(self, environment=True):
        if not self.path.exists():
            # 旧项目/便携包配置只导入一次，以后全部读用户目录。
            source = Path(resource_path("config.json"))
            if getattr(__import__("sys"), "frozen", False):
                portable = Path(__import__("sys").executable).parent / "config.json"
                if portable.exists():
                    source = portable
            raw = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
            cfg = config_from_dict(raw)
            self.save(cfg)
        else:
            cfg = config_from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        return apply_environment(cfg) if environment else cfg

    def save(self, cfg):
        validate_config(cfg)
        atomic_json(self.path, asdict(cfg))
