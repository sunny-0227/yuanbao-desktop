"""确定性指令识别：明确动作才执行，否定、解释与引用优先交给对话。"""

import ntpath
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CommandResult:
    handled: bool
    action: Optional[str] = None
    data: dict = field(default_factory=dict)
    confirmation: bool = False


class CommandRouter:
    def route(self, text):
        raw = text.strip().strip("。！! ")
        norm = re.sub(r"^(请|帮我|麻烦你|麻烦|元宝)[，,\s]*", "", raw)
        if not norm or re.search(
            r"不要|别(?:给我|帮我)?|不需要|不想|禁止|不用|解释|为什么|如何|怎么|写一|帮我写|生成|总结|翻译|分析",
            norm,
        ):
            return CommandResult(False)

        def hit(action, data=None, confirm=False):
            return CommandResult(True, action=action, data=data or {}, confirmation=confirm)

        if norm.rstrip("？?") in (
            "打开了吗",
            "打开了嘛",
            "打开了么",
            "打开了没",
            "打开没有",
            "打开了没有",
            "启动了吗",
            "启动成功了吗",
            "打开成功了吗",
            "刚才打开了吗",
            "有没有打开",
            "软件打开了吗",
        ):
            return hit("check_open")

        # 明确的路径启动命令优先识别；引号是路径定界符，不应使请求落入AI聊天。
        explicit = re.fullmatch(r"(?:打开|启动|运行)\s*(.+)", norm)
        suffix = re.fullmatch(r"(.+?)\s*(?:打开|启动|运行)", norm)
        target = (explicit[1] if explicit else suffix[1] if suffix else "").strip()
        if target:
            target = re.sub(r"\s*(?:这个|这个软件|这个程序)$", "", target).strip()
            pairs = {'"': '"', "'": "'", "“": "”", "‘": "’"}
            if target[:1] in pairs and target.endswith(pairs[target[0]]):
                target = target[1:-1].strip()
            drive, rest = ntpath.splitdrive(target)
            if (
                drive
                and rest.startswith(("\\", "/"))
                and not any(c in target for c in ('"', "'", "“", "”", "\n", "\r"))
            ):
                return hit("open_path", {"path": target})
        if re.search(r"[“”\"‘’]", norm):
            return CommandResult(False)

        path_query = re.fullmatch(
            r"(?:(?:你)?(?:帮我)?(?:找一下|找下|查一下|查下|查找|查询|查|查看|找)(?:我)?\s*(.+?)(?:的)?(?:安装路径|安装位置|路径|地址|位置)|(.+?)(?:的)?(?:安装路径|安装位置|路径|地址|位置)(?:在哪(?:里)?|是什么))",
            norm,
        )
        if path_query:
            name = (path_query[1] or path_query[2]).strip().rstrip("的")
            return hit("find_app", {"name": name})

        if norm in ("取消静音", "恢复声音", "打开声音", "取消消音"):
            return hit("unmute")
        if norm in ("静音", "关闭声音", "关声音", "消音"):
            return hit("mute")
        if norm in (
            "截图",
            "截个图",
            "截一下屏",
            "保存截图",
            "屏幕截图",
            "抓屏",
            "截屏",
            "截一张图",
        ):
            return hit("screenshot")
        if norm in ("锁屏", "锁定屏幕", "锁定电脑", "锁一下屏"):
            return hit("lock")
        if norm in ("暂停播放", "暂停音乐", "播放音乐", "继续播放", "下一曲", "上一曲"):
            return hit(
                "media",
                {
                    "key": "next"
                    if norm == "下一曲"
                    else "previous"
                    if norm == "上一曲"
                    else "play_pause"
                },
            )
        if norm in ("进入休眠", "休眠", "元宝休息"):
            return hit("sleep")
        if norm in ("恢复工作", "唤醒助手"):
            return hit("wake")
        if norm in (
            "几点了",
            "现在几点",
            "现在时间",
            "今天几号",
            "今天星期几",
            "今天周几",
            "查询时间",
            "查看日历",
            "今天日期",
        ):
            return hit("datetime")
        if norm in (
            "电脑状态",
            "查看电脑状态",
            "系统状态",
            "查看系统资源",
            "资源占用",
            "查看CPU",
            "查看内存",
            "查看电量",
            "电池电量",
            "查看磁盘",
        ):
            return hit("status")
        if norm in ("查看笔记", "看看笔记", "笔记列表", "我的笔记", "显示笔记"):
            return hit("notes")
        if norm in (
            "查看提醒",
            "提醒列表",
            "我的提醒",
            "查看待办",
            "待办列表",
            "我的待办",
            "查一下提醒",
        ):
            return hit("todos")
        if norm in ("清空笔记", "删除全部笔记", "清空所有笔记"):
            return hit("clear_notes", confirm=True)
        if norm == "清空回收站":
            return hit("recycle", confirm=True)
        if norm in ("取消关机", "取消重启", "取消定时关机"):
            return hit("cancel_shutdown")
        m = re.fullmatch(r"(?:(\d+)分钟后)?(关机|重启)", norm)
        if m:
            return hit(
                "shutdown", {"seconds": int(m[1] or 1) * 60, "restart": m[2] == "重启"}, True
            )
        m = re.fullmatch(r"(?:调高音量|音量增加|声音大一点|加大音量)(?:\s*(\d+)%?)?", norm)
        if m:
            return hit("volume_up", {"amount": min(int(m[1] or 10), 100)})
        m = re.fullmatch(r"(?:调低音量|音量降低|声音小一点|降低音量)(?:\s*(\d+)%?)?", norm)
        if m:
            return hit("volume_down", {"amount": min(int(m[1] or 10), 100)})
        m = re.fullmatch(r"(?:删除|取消|移除)(?:提醒|待办)\s*#?(\d+)", norm)
        if m:
            return hit("delete_todo", {"id": int(m[1])}, True)
        m = re.fullmatch(r"完成(?:提醒|待办)\s*#?(\d+)", norm)
        if m:
            return hit("complete_todo", {"id": int(m[1])})
        if re.search(r"提醒我|帮我提醒|设个提醒|添加提醒|定个提醒|记个提醒|提醒一下", norm):
            return hit("add_todo", {"text": raw})
        for prefix in ("记一下", "记下", "记录一下", "记录", "备忘", "备注", "记个事"):
            if norm.startswith(prefix):
                return hit("add_note", {"content": norm[len(prefix) :].lstrip(" ：:")})
        m = re.fullmatch(r"(?:搜索|搜一下|百度一下|必应搜索|谷歌搜索|查找)\s*(.+)", norm)
        if m:
            return hit(
                "search",
                {
                    "query": m[1],
                    "engine": "baidu"
                    if norm.startswith("百度")
                    else "google"
                    if norm.startswith("谷歌")
                    else "",
                },
            )
        m = re.fullmatch(r"(?:打开|启动|运行)\s*(.+)", norm)
        if m:
            name = re.sub(r"^(?:桌面上的|桌面上|桌面的|我桌面上的|电脑上的)", "", m[1]).strip()
            return hit("open", {"name": name})
        m = re.fullmatch(r"(?:关闭|退出软件)\s*(.+)", norm)
        if m:
            return hit("close_app", {"name": m[1]}, True)
        m = re.fullmatch(r"(?:新建文件夹|创建文件夹)\s*(.+)", norm)
        if m:
            return hit("mkdir", {"path": m[1]})
        m = re.fullmatch(r"(?:计算|算一下)\s*(.+)", norm)
        if m:
            return hit("calculate", {"expression": m[1]})
        m = re.fullmatch(r"(?:查询|查看)?(.{1,30}?)(?:的)?天气", norm)
        if m:
            return hit("weather", {"city": m[1]})
        return CommandResult(False)
