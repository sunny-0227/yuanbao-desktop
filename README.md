# 元宝桌面助手

<img src="assets/brand/selected/logo.png" width="144" alt="元宝Logo">

我想做一个常驻桌面的轻量助手：需要时说一句话，帮我打开软件、记录想法、设置提醒，或者接着上一次对话聊下去；不用时就收进托盘，尽量减少后台占用。

元宝用 **Python + PySide6** 开发，面向 **Windows 10/11**。这是我的个人vibe coding项目，目前还在持续完善。对话、提醒、笔记和设置已经集中到同一个工作台，桌面形象已接入待机、聆听、思考、播报和执行动画，休眠时保持静态。

英文项目标识：`yuanbao-desktop`。原型是我养的一只猫咪叫 **元宝**，是一只 **长毛金虎斑猫**。

最终选择B2作为Logo与角色基准。界面沿用深青绿、暖奶油与金焦糖的品牌配色，支持浅色和深色主题。

[品牌配色与状态预览](assets/brand/selected/preview.html) · [素材说明](docs/asset-requirements.md) · [早期Logo候选](assets/brand/logo-candidates/README.md)

## 目前能做什么

| 功能 | 说明 |
|---|---|
| AI对话 | 兼容Chat Completions工具调用，统一理解多轮对话、执行工具、接收实际结果并保留任务状态 |
| 本地操作 | 打开软件、文件和文件夹，搜索、截图、音量控制、锁屏、媒体控制和电脑状态查询 |
| 待办与提醒 | 单次、每日、每周、间隔提醒，支持完成、稍后提醒、弹窗和可选语音播报 |
| 随手笔记 | 本地记录、搜索、编辑和删除 |
| 语音输入 | 在线识别、Faster-Whisper离线识别，以及可选的Vosk语音唤醒 |
| 语音播报 | Edge在线播报与系统离线播报 |
| 桌面入口 | 悬浮窗口、拖拽吸附、边缘收纳、系统托盘、位置记忆和可选开机启动 |
| 省电与休眠 | 空闲省电、高负载自动休眠、软件黑白名单和手动恢复 |

本地指令不依赖AI服务。清空笔记、清空回收站、关闭软件、删除提醒和安排关机/重启，需要先在界面确认。

从2.1版开始，对话统一进入协调层。连接模型时，由模型结合会话和任务状态选择受限工具，程序校验参数后执行，并把真实回执交回对话。候选软件、提醒草稿、当前记录和待确认操作按会话保存；普通聊天文字不能冒充执行记录。没有连接模型或接口故障时，明确的本机指令通过同一套工具降级执行，不能替代完整自然语言理解。模型生成的文字不会被当成shell或代码运行。

启动软件会区分“已发送请求”“检测到运行进程”“检测到可见窗口”，不会仅凭启动API返回就报告成功。支持带空格和引号的Windows完整路径、快捷方式参数，以及“打开了吗”“没有弹窗”等对当前任务的追问。删除、清空、关闭软件和关机等操作仍需在界面确认。

打开软件会自动查找桌面、开始菜单、Windows应用注册信息和运行中的程序位置，支持自定义安装目录、移动后的桌面及OneDrive桌面。快捷方式改名时，还会结合目标exe名称和文件自身的描述、原始文件名查找；套件会在注册安装目录内识别子程序。旧配置路径失效时会重新识别并缓存实际位置，不需要逐个填写安装路径。可以说“打开桌面上的微信”，也可以说“你找下我微信路径”仅查询位置。多个同名安装位置会先列出；没有注册信息或快捷方式的便携软件，可以先把快捷方式放到桌面。

对话采用左右气泡：我的消息在右侧，元宝的回复在左侧。支持Markdown和文本复制，向上翻阅时不会持续跳回底部；工具调用阶段先核实实际结果，再展示执行回复。

## 快速开始

准备64位Windows，以及Python 3.11或3.12。下载源码后，可以直接运行：

```bat
scripts\run_windows.bat
```

脚本会创建虚拟环境、安装核心依赖并启动。也可以手动执行：

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-base.txt -r requirements-win.txt
.venv\Scripts\python main.py
```

进入「设置 → AI连接」，填写API根地址、密钥和模型名称，点击“测试连接与工具调用”。所选模型和接口转发服务都需要支持Chat Completions的`tools/tool_calls`协议；仅能返回聊天文字的接口不能作为完整执行助手。测试不会操作桌面。也可以复制 `.env.example` 为 `.env`，通过环境变量配置；环境变量的优先级高于界面设置。

没有配置AI时，仍能使用本地操作、笔记与提醒。接口费用和免费额度取决于所选服务商。

## 试着说这些

```text
打开计算器
搜索 Python 教程
查看电脑状态
取消静音
截图
十分钟后提醒我喝水
明天下午3点提醒我开会
每天18:30提醒我休息
每周一9点提醒我开会
记一下 下周整理项目资料
计算 (2+3)*4
查询厦门天气
```

打开软件时，可以使用设置中的快捷入口，或者先扫描桌面与开始菜单的快捷方式。天气查询使用Open-Meteo，需要联网。

工作台中的提醒和笔记可以直接管理，不必全部通过聊天操作。提醒弹出后还可以标记完成，或推迟10分钟。

关闭工作台会收进托盘；选择托盘菜单里的「退出程序」才会退出。点击「停止」可以取消当前请求，但已经完成的本地操作不会撤回。

## 可选语音功能

我把语音依赖单独拆出来，默认关闭。需要录音、在线识别和播报时安装：

```bat
.venv\Scripts\python -m pip install -r requirements-voice.txt
```

然后在设置中选择识别与播报方式：

- **在线识别**：使用兼容 `/audio/transcriptions` 的接口。
- **Edge-TTS**：需要联网，支持配置音色。
- **系统TTS**：使用电脑上的离线语音。

需要本地Whisper识别或Vosk唤醒时，再安装：

```bat
.venv\Scripts\python -m pip install -r requirements-voice-local.txt
```

模型需要另行准备，在设置中填写已下载的Whisper模型和已解压的Vosk中文模型目录。程序不会自动下载模型。Whisper在独立子进程里按需运行，识别结束或取消后结束进程；唤醒监听会在省电、休眠和任务执行时暂停。

## 数据放在哪里

运行数据默认保存在：

```text
%LOCALAPPDATA%\Yuanbao
```

用户设置、笔记、提醒、会话和扫描结果都保存在本机。AI对话和在线语音识别会把相应的文本或音频发送给配置的服务，天气查询会发送城市名称。

仓库中的 `config.json` 是分发默认配置，运行后的设置保存在用户目录，不会写入exe的临时解压目录。旧版JSON数据也保留了一次性迁移入口。需要指定独立数据目录时，可以设置 `YUANBAO_DATA_DIR`。旧版 `TUTU_DATA_DIR` 仍可使用；如果已存在旧版 `TutuAssistant` 用户数据且新目录尚无数据，程序会继续读取原目录，保留设置与记录。

`.env`、数据库、日志、模型和本地助手记录已加入忽略规则。发布仓库时只保留无密钥模板；实际密钥可以放在环境变量或本机用户配置中。

## 项目结构

```text
app/         配置、数据存储、状态与应用控制器
services/    指令、AI、语音、提醒和系统操作
ui/          工作台、设置、悬浮窗口与托盘
assets/      后续补充的形象与图标
scripts/     Windows运行、构建和界面检查
tests/      核心回归测试
docs/       架构、素材要求和验收说明
```

界面通过Qt信号与业务交互，耗时任务在后台队列处理。配置采用原子写入，笔记、提醒和聊天记录使用SQLite事务。更详细的设计见 [架构说明](docs/architecture.md)。

## 测试与打包

GitHub Actions通过Windows测试后，会生成单文件核心版 `Yuanbao.exe`。在仓库 **Actions → 最新成功的 Windows checks → Artifacts** 下载 `Yuanbao-Windows-x64`，解压后即可运行，无需安装Python。下载附件需要登录GitHub，保留30天。此版本不含语音依赖；需要录音与播报时按下面的 `--voice` 方式构建。

安装开发依赖后执行：

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check app services ui main.py scripts tests
```

核心测试可以在macOS上使用隔离数据运行；Windows界面、系统控制、麦克风和实际模型需要在Windows环境验证。仓库已配置Windows CI，完整手动检查见 [Windows验收](docs/windows-acceptance.md)。

Windows打包：

```bat
scripts\build_windows.bat
```

默认输出 `dist\Yuanbao\Yuanbao.exe`。可选参数：

```bat
scripts\build_windows.bat --onefile
scripts\build_windows.bat --voice
scripts\build_windows.bat --local-voice
```

核心包不包含语音依赖；`--voice` 包含录音与播报，`--local-voice` 额外包含本地识别依赖。模型和密钥始终外置，Windows exe需要在Windows构建。

## 接下来想完善的部分

- 完善麦克风切换和录音结束判断。
- 根据实际体验继续调整工作台和后台运行方式。

当前代码和核心测试不代表已经完成所有Windows整机验证。我会把已实现功能与后续计划分开记录，随着测试结果继续更新。

开发约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。欢迎通过Issue反馈问题或提出建议。
