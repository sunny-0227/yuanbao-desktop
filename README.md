# 轻量化桌面AI效率助手

> 基于 Python + PySide6 开发的 Windows 桌面端 AI 效率助手  
> 支持悬浮助手、系统托盘、快捷指令、AI 问答与自动休眠

---

## 项目简介

这是一个运行在 Windows 桌面的轻量级 AI 效率工具。常驻系统托盘，提供悬浮式桌面助手形象，用户通过自然语言聊天窗口即可快速完成：打开常用软件、搜索网页、记录笔记、设置待办提醒、截图保存、查询电脑状态、发起 AI 问答等日常效率操作。同时内置资源监测与自动休眠机制，在高负载或长时间空闲时主动降低资源占用。

---

## 功能特点

| 功能模块 | 说明 |
|----------|------|
| 🐾 桌面悬浮助手 | 无边框透明窗口，始终置顶，可拖拽，双击打开对话 |
| 🖥️ 系统托盘 | 右键菜单快速访问全部功能，支持休眠/恢复/退出 |
| 🚀 快捷应用启动 | 通过聊天指令一键打开微信、浏览器、Word 等常用软件 |
| 📂 快捷文件夹 | 快速打开桌面、下载、文档、项目等常用目录 |
| 🔍 网页搜索 | 支持 Bing / Baidu / Google，直接在浏览器中打开 |
| 📝 快速笔记 | 随时记录零散想法，持久化到本地 JSON 文件 |
| ⏰ 待办提醒 | 自然语言设置提醒，到点桌面弹窗通知 |
| 📷 截图保存 | 一键全屏截图，自动保存到指定目录 |
| 🤖 AI 文本问答 | 接入 OpenAI 兼容接口，支持缓存加速 |
| 💻 电脑状态查询 | 实时查询 CPU、内存、磁盘、电池信息 |
| 😴 高负载自动休眠 | CPU 超阈值或检测到黑名单进程时自动进入休眠模式 |
| ⚙️ 图形化设置 | 可视化修改常用配置，无需手动编辑 JSON |

---

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.11 | 主语言 |
| PySide6 | 桌面 GUI 框架（Qt6 官方绑定） |
| httpx | 调用 AI API（异步 HTTP 请求） |
| psutil | 系统资源监测（CPU / 内存 / 磁盘 / 进程） |
| python-dotenv | 加载 `.env` 中的 API Key 等敏感配置 |
| Pillow | 截图功能（ImageGrab） |
| pycaw | Windows 系统音量控制 |
| PyInstaller | 打包为单文件 exe |

---

## 目录结构

```
tutu/
├── main.py                    # 应用入口，初始化所有组件
├── config.json                # 应用配置文件（快捷应用、搜索引擎等）
├── .env                       # 敏感配置（AI API Key，不提交到 Git）
├── .env.example               # .env 模板示例
├── requirements-base.txt      # 跨平台基础依赖
├── requirements-win.txt       # Windows 专属依赖
│
├── app/                       # 核心应用层
│   ├── app_context.py         # 统一资源路径工具（开发/打包双兼容）
│   ├── config.py              # 配置加载，提供类型安全的 dataclass
│   ├── state_manager.py       # 全局状态管理（active/idle/sleep）
│   ├── logger.py              # 统一日志配置
│   └── utils.py               # 平台检测等通用工具
│
├── services/                  # 业务服务层
│   ├── command_router.py      # 用户输入路由（关键词匹配 → action）
│   ├── command_dispatcher.py  # 指令分发（action → Service 调用）
│   ├── local_command_executor.py  # 后台线程异步执行，防止 UI 阻塞
│   ├── app_command_service.py # 打开应用 / 文件夹
│   ├── search_service.py      # 网页搜索
│   ├── note_service.py        # 快速笔记（data/notes.json）
│   ├── todo_service.py        # 待办提醒（data/todos.json）
│   ├── screenshot_service.py  # 截图保存
│   ├── monitor_service.py     # 系统资源查询 + 自动休眠数据源
│   ├── auto_sleep_service.py  # 自动休眠检测逻辑
│   ├── system_service.py      # 音量控制 / 锁屏
│   ├── ai_service.py          # AI 问答（httpx，兼容 OpenAI 接口）
│   └── cache_service.py       # AI 回复本地缓存（data/chat_cache.json）
│
├── ui/                        # 界面层
│   ├── floating_pet.py        # 桌面悬浮助手窗口
│   ├── tray_menu.py           # 系统托盘菜单
│   ├── chat_window.py         # 聊天对话窗口
│   ├── settings_window.py     # 设置窗口
│   ├── reminder_popup.py      # 待办到点弹窗
│   ├── message_bubble.py      # 聊天气泡组件
│   └── style.py               # 深色 / 浅色主题 QSS 样式
│
├── data/                      # 运行时数据（自动创建）
│   ├── notes.json             # 笔记数据
│   ├── todos.json             # 待办数据
│   ├── chat_cache.json        # AI 回复缓存
│   ├── command_rules.json     # 指令匹配规则
│   └── app.log                # 运行日志
│
├── assets/                    # 静态资源
│   ├── icons/                 # 应用图标（app.ico、app_icon.ico）
│   └── pet/                   # 宠物状态图片（idle/thinking/speaking/sleep）
│
└── scripts/                   # 辅助脚本
    ├── run_windows.bat        # Windows 一键运行脚本
    └── build_windows.bat      # Windows exe 打包脚本
```

---

## 快速开始（Windows）

### 方式一：一键运行（推荐）

```bat
:: 双击运行，或在 cmd 中执行
scripts\run_windows.bat
```

脚本会自动完成：创建虚拟环境 → 安装依赖 → 启动程序。

### 方式二：手动运行

```bat
:: 1. 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate

:: 2. 安装依赖
pip install -r requirements-base.txt
pip install -r requirements-win.txt

:: 3. 配置 AI（可选，见下方 .env 说明）
copy .env.example .env
:: 编辑 .env，填写 AI_API_KEY 等

:: 4. 启动
python main.py
```

---

## 打包为 exe（Windows）

```bat
:: 双击运行，或在 cmd 中执行
scripts\build_windows.bat
```

打包完成后，可执行文件位于：

```
dist\TutuAssistant.exe
```

> **注意**：打包前请确保已安装 `requirements-win.txt`（含 PyInstaller）。  
> 发布时需将 `.env` 文件放在 `TutuAssistant.exe` 同目录，AI 功能才能正常工作。

---

## 配置说明

### config.json 常用字段

打开「系统托盘 → 打开设置」可通过图形界面修改，也可直接编辑文件：

| 字段路径 | 说明 | 默认值 |
|----------|------|--------|
| `search.engine` | 默认搜索引擎 | `"bing"` |
| `screenshot.save_dir` | 截图保存目录 | `~/Pictures/TutuAssistantScreenshots` |
| `behavior.cpu_sleep_threshold` | CPU 超过此值自动休眠（%） | `80` |
| `behavior.idle_sleep_minutes` | 空闲超过此时间进入 idle（分钟，0=禁用） | `10` |
| `behavior.blacklist_processes` | 检测到这些进程时自动休眠 | `["explorer.exe"]` |
| `ai.enable_ai_cache` | 是否缓存 AI 回复 | `true` |
| `quick_apps` | 快捷应用列表，每项含 `name` 和 `command` | 见文件 |
| `quick_folders` | 快捷文件夹列表，每项含 `name` 和 `path` | 见文件 |

**quick_apps 示例：**

```json
"quick_apps": [
  { "name": "微信", "command": "%USERPROFILE%\\AppData\\Roaming\\Tencent\\WeChat\\WeChat.exe" },
  { "name": "浏览器", "command": "" }
]
```

**quick_folders 示例：**

```json
"quick_folders": [
  { "name": "项目", "path": "%USERPROFILE%\\Projects" }
]
```

### .env 配置（AI 功能）

复制 `.env.example` 为 `.env`，填写以下字段：

```env
# AI 接口地址（留空则默认使用 OpenAI 官方地址）
AI_API_BASE_URL=https://api.openai.com/v1

# AI API Key（必填，才能使用 AI 问答）
AI_API_KEY=sk-xxxxxxxxxxxxxxxx

# 使用的模型名称
AI_MODEL_NAME=gpt-4o-mini
```

> `.env` 文件已加入 `.gitignore`，不会提交到版本库。  
> 兼容 OpenAI、DeepSeek、本地 Ollama 等所有支持 Chat Completions 格式的接口。

---

## 常见问题

**Q：为什么在 Mac 上只写代码而不运行？**  
A：本项目的核心功能（音量控制 `pycaw`、系统托盘图标样式、`os.startfile` 文件打开等）深度依赖 Windows API，在 macOS 上无法完整运行。Mac 侧仅用于代码开发，实际测试需在 Windows 环境进行。

**Q：为什么 exe 要在 Windows 上打包，不能在 Mac 上打包？**  
A：PyInstaller 只能打包当前运行平台对应的可执行文件。Mac 上的 PyInstaller 只能生成 macOS 可执行文件，无法生成 Windows `.exe`。

**Q：没有 AI API Key，程序能正常使用吗？**  
A：可以。本地指令（打开应用、搜索、笔记、截图、待办等）完全不依赖 AI，正常可用。未配置 API Key 时，聊天窗口会有提示，AI 问答功能不可用，其他功能不受影响。

**Q：配置了快捷应用路径，但打开失败怎么办？**  
A：请检查 `config.json` 中 `quick_apps` 里对应应用的 `command` 路径是否正确，路径支持 Windows 环境变量（如 `%USERPROFILE%`）。可先在 cmd 中直接运行该命令验证。

**Q：打包后运行提示找不到 config.json 或图片资源怎么办？**  
A：项目使用 `app/app_context.py` 中的 `resource_path()` 统一处理资源路径，打包时已通过 `--add-data` 将 `assets`、`data`、`config.json` 一起打入 exe。若仍报错，请检查 `build_windows.bat` 中的 `--add-data` 参数是否完整。

**Q：pycaw 或 pywin32 安装失败怎么办？**  
A：请确认在 Windows 环境下安装，且 Python 版本为 3.11。可尝试先升级 pip：`python -m pip install --upgrade pip`，再重新安装。如果通过国内网络安装缓慢，可添加镜像源：`pip install pycaw -i https://pypi.tuna.tsinghua.edu.cn/simple`。

---

## 项目经历描述（简历参考）

**轻量化桌面AI效率助手** | Python / PySide6 / Windows 桌面开发

- 独立设计并实现一款 Windows 桌面端 AI 效率工具，采用模块化架构，将 UI 层（PySide6）、服务层（各业务 Service）、核心层（配置/状态/日志）清晰分离，代码共约 3000+ 行。
- 实现基于关键词规则的自然语言指令路由（CommandRouter），支持 20+ 种本地操作指令，覆盖应用启动、文件夹打开、网页搜索、快速笔记、待办提醒、截图、系统状态查询等高频场景。
- 接入 OpenAI 兼容 AI 接口（httpx），实现后台线程异步执行，配合本地 JSON 缓存机制（CacheService），在不阻塞 UI 的前提下提供 AI 问答能力。
- 基于 psutil 实现系统资源监测与自动休眠服务（AutoSleepService），支持 CPU 阈值触发、黑名单进程检测和空闲超时降级，通过 StateManager 统一管理 active/idle/sleep 三种状态，解耦 UI 与业务逻辑。
- 使用 PySide6 的 QThread + Signal/Slot 机制保障所有耗时操作异步执行，全程不阻塞主界面；采用 QSystemTrayIcon 实现常驻系统托盘，使用无边框透明窗口实现桌面悬浮助手形象。
- 使用 PyInstaller 打包为单文件 Windows exe，通过自编 bat 脚本实现一键开发运行与一键打包，降低部署门槛。

---

## 注意事项

- 本项目仅用于**学习和个人项目经历展示**，不建议直接用于商业产品。
- 宠物形象资源（`assets/pet/`）请自行准备，项目代码不包含任何受版权保护的第三方卡通形象素材。
- `.env` 文件含有 API Key 等敏感信息，**严禁提交到公开代码仓库**。
- `pycaw`、`pywin32` 等 Windows 专属依赖仅在 Windows 环境下有效，macOS/Linux 运行时相关功能会优雅降级并给出提示。

---

## License

MIT License — 仅供学习参考，使用请遵守相关依赖库的开源协议。
