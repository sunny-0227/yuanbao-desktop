# 元宝素材与品牌说明

正式方案已选定B2，角色是项目作者饲养的长毛金虎斑猫元宝。应用图标、六个桌宠静态状态与界面主题已采用同一角色和品牌配色。

## 已接入的文件

| 文件 | 用途 |
|---|---|
| `assets/brand/selected/logo.png` | B2原始Logo，1254×1254 |
| `assets/icons/app_icon.png` | 应用图标原始PNG，与B2内容一致 |
| `assets/icons/app_icon.ico` | Windows图标导出，16–256像素 |
| `assets/pet/default/idle.png` | 待机 |
| `assets/pet/default/listening.png` | 聆听 |
| `assets/pet/default/thinking.png` | 思考 |
| `assets/pet/default/speaking.png` | 播报 |
| `assets/pet/default/working.png` | 执行 |
| `assets/pet/default/sleep.png` | 休眠 |
| `assets/pet/default/idle-animation/` | 59帧透明待机动画试样，480×480、12fps |
| `assets/pet/default/listening-animation/` | 聆听透明动作序列 |
| `assets/pet/default/thinking-animation/` | 思考透明动作序列 |
| `assets/pet/default/speaking-animation/` | 播报透明动作序列，非逐字口型同步 |
| `assets/pet/default/working-animation/` | 执行透明动作序列 |
| `assets/pet/default/sleep-animation/` | 休眠透明序列，软件仅显示首帧以停止刷新 |

六个状态均为1254×1254的RGBA透明PNG，通过内置imagegen基于B2和同一张待机基准制作。图片保留原始输出；ICO只做文件格式与标准图标尺寸导出。提示词和生成元数据在`assets/pet/prompts/`。

[品牌与状态预览](../assets/brand/selected/preview.html) 可切换浅/深主题，用于查看配色，不是Windows软件截图。

[六种动作预览](../assets/brand/selected/animation-preview.html) 可切换动作、背景与显示尺寸，用于检查抠图和循环，不是Windows软件截图。六套序列均为59帧、480×480、12fps。源视频开头去掉4帧，按各段蓝底分别抠图后增加透明留白，休眠的蓝色阴影一并去除。运行时正放再倒放，按各状态元数据停顿；默认皮肤五种活动状态播放，休眠只显示首帧。隐藏和收纳停止计时，缺帧或无效元数据回落静态图。预览页可单独播放休眠呼吸素材。

## 统一配色

深青绿`#315D59`、金焦糖`#C98A3A`、暖奶油`#F5E3B9`组成品牌色。主按钮和选中状态沿用青绿，浅色界面用暖白/奶油，金色用于少量角色标签与强调。深色主题使用同一色系。语义色集中在`ui/brand.py`。

正文、次要文字、主按钮与标签的代表性前景/背景组合均检查达到4.5:1对比度，实际Windows渲染仍需验收。

## 后续可以补充

- 验证各状态动画的Windows显示效果，补充点击反馈与拖动反馈。
- 播报口型同步、异常与断网状态。
- 其他皮肤。每套沿用相同画布、基线和角色比例。

动画使用透明PNG序列，当前12fps，休眠保持静态。各目录metadata.json记录帧数、帧率、是否播放、循环方式、停顿和源文件校验值。播放器已支持上述六种状态；逐字口型同步尚未实现。

## 语音模型与服务

图片素材已齐备，语音/AI仍需自行配置相应服务或模型：兼容Chat Completions的AI接口、兼容`/audio/transcriptions`的在线ASR、已下载的Faster-Whisper模型、Vosk中文唤醒模型。离线聊天可连接已运行的兼容本地模型服务。
