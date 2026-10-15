"""提醒服务：自然时间、重复提醒、通知确认、完成与稍后提醒。"""

import re
from datetime import datetime, timedelta

from app.storage import Database

FMT = "%Y-%m-%d %H:%M:%S"


def _number(text):
    if text.isdigit():
        return int(text)
    digits = {c: i for i, c in enumerate("零一二三四五六七八九")}
    digits["两"] = 2
    if text == "半":
        return 0.5
    if "十" in text:
        a, b = text.split("十", 1)
        return (digits.get(a, 1) * 10) + digits.get(b, 0)
    if text in digits:
        return digits[text]
    raise ValueError("暂不支持这个数字，请使用阿拉伯数字")


def parse_reminder(text, now=None):
    """优先解析完整日期/相对时间，拒绝过去或非法日期，绝不忽略日期降级。"""
    now = now or datetime.now()
    source = text.strip()
    recurrence = ""
    match = re.search(r"每隔([\d零一二两三四五六七八九十半]+)(分钟|小时|天)", source)
    relative = re.search(r"([\d零一二两三四五六七八九十半]+)(分钟|小时|天)后", source)
    date = re.search(r"(\d{4}-\d{1,2}-\d{1,2})\s+(\d{1,2}[:：]\d{2})", source)
    consumed = []
    if match or relative:
        m = match or relative
        seconds = _number(m[1]) * {"分钟": 60, "小时": 3600, "天": 86400}[m[2]]
        if seconds < 60 or seconds > 365 * 86400:
            raise ValueError("提醒间隔需在 1 分钟到 365 天之间")
        due = now + timedelta(seconds=seconds)
        if match:
            recurrence = f"interval:{int(seconds)}"
        consumed.append(m.group())
    elif date:
        due = datetime.strptime(date[1] + " " + date[2].replace("：", ":"), "%Y-%m-%d %H:%M")
        consumed.append(date.group())
    else:
        clock_source = re.sub(r"每周[一二三四五六日天]", "", source)
        time = re.search(r"(\d{1,2})[:：](\d{2})", clock_source)
        chinese = re.search(
            r"([\d零一二两三四五六七八九十]+)[点时](半|[\d零一二两三四五六七八九十]+分?)?",
            clock_source,
        )
        if not time and not chinese:
            raise ValueError(
                "请带上时间，例如：十分钟后提醒我喝水、明天下午3点提醒我开会、每天18:30提醒我休息"
            )
        hour = int(time[1]) if time else int(_number(chinese[1]))
        minute = (
            int(time[2])
            if time
            else (
                30
                if chinese[2] == "半"
                else int(_number(chinese[2].rstrip("分")))
                if chinese[2]
                else 0
            )
        )
        if any(word in source for word in ("下午", "晚上", "傍晚")) and hour < 12:
            hour += 12
        if "凌晨" in source and hour == 12:
            hour = 0
        days = 2 if "后天" in source else 1 if "明天" in source else 0
        due = (now + timedelta(days=days)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if "每天" in source:
            recurrence = "daily"
        elif "每周" in source:
            week = re.search(r"每周([一二三四五六日天])", source)
            if not week:
                raise ValueError("每周提醒请指定星期，例如：每周一9点提醒我开会")
            target = "一二三四五六日".index(week[1].replace("天", "日"))
            due += timedelta(days=(target - due.weekday()) % 7)
            recurrence = "weekly"
            consumed.append(week.group())
        if due <= now:
            if days or "今天" in source:
                raise ValueError("提醒时间已经过去，请选择未来时间")
            due += timedelta(days=7 if recurrence == "weekly" else 1)
        consumed.append((time or chinese).group())
    if due <= now:
        raise ValueError("提醒时间已经过去，请选择未来时间")
    title = source
    for part in consumed:
        title = title.replace(part, "", 1)
    title = re.sub(
        r"每天|今天|明天|后天|下午|上午|晚上|早上|中午|傍晚|凌晨|提醒一下|帮我提醒|提醒我|设个提醒|添加提醒|定个提醒|记个提醒",
        "",
        title,
    )
    title = title.strip(" ，,。:：")
    if not title:
        raise ValueError("请填写提醒内容")
    return {"title": title, "remind_time": due.strftime(FMT), "recurrence": recurrence}


class TodoService:
    def __init__(self, db=None):
        self.db = db or Database()

    def add(self, title, remind_time, recurrence=""):
        title = title.strip()
        due = datetime.fromisoformat(remind_time)
        if not title or due <= datetime.now():
            raise ValueError("请填写内容和未来的提醒时间")
        if recurrence not in ("", "daily", "weekly") and not re.fullmatch(
            r"interval:[1-9]\d*", recurrence
        ):
            raise ValueError("无效循环规则")
        with self.db.connect() as conn:
            return conn.execute(
                "INSERT INTO todos(title,remind_time,recurrence,created_at) VALUES (?,?,?,?)",
                (title, due.strftime(FMT), recurrence, datetime.now().strftime(FMT)),
            ).lastrowid

    def add_todo_from_text(self, text):
        parsed = parse_reminder(text)
        ident = self.add(**parsed)
        label = "（循环）" if parsed["recurrence"] else ""
        return f"已设置提醒 #{ident}：{parsed['title']}\n{parsed['remind_time']}{label}"

    def all(self):
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM todos ORDER BY status='completed',remind_time,id"
                )
            ]

    def list_todos(self):
        rows = [r for r in self.all() if r["status"] != "completed"]
        return (
            "暂无待办提醒。"
            if not rows
            else "\n".join(
                f"#{r['id']} {r['remind_time']} · {r['title']} [{r['status']}]" for r in rows
            )
        )

    def delete_todo(self, todo_id):
        with self.db.connect() as conn:
            count = conn.execute("DELETE FROM todos WHERE id=?", (todo_id,)).rowcount
        return "已删除提醒。" if count else "找不到这条提醒。"

    def complete(self, todo_id):
        with self.db.connect() as conn:
            conn.execute("UPDATE todos SET status='completed' WHERE id=?", (todo_id,))

    def snooze(self, todo_id, minutes=10):
        due = (datetime.now() + timedelta(minutes=minutes)).strftime(FMT)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE todos SET status='pending',remind_time=?,notified_at=NULL WHERE id=?",
                (due, todo_id),
            )

    def check_due_todos(self, now=None):
        """只查询；通知实际发出后调用 acknowledge，失败不会丢掉提醒。"""
        now = now or datetime.now()
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM todos WHERE status='pending' AND remind_time<=? ORDER BY remind_time",
                    (now.strftime(FMT),),
                )
            ]

    def acknowledge(self, todo_id, now=None):
        now = now or datetime.now()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM todos WHERE id=? AND status='pending'", (todo_id,)
            ).fetchone()
            if not row:
                return
            recurrence = row["recurrence"]
            if recurrence:
                seconds = (
                    86400
                    if recurrence == "daily"
                    else 604800
                    if recurrence == "weekly"
                    else int(recurrence.split(":")[1])
                )
                due = datetime.fromisoformat(row["remind_time"])
                due += timedelta(
                    seconds=(int((now - due).total_seconds() // seconds) + 1) * seconds
                )
                conn.execute(
                    "UPDATE todos SET remind_time=?,notified_at=? WHERE id=?",
                    (due.strftime(FMT), now.strftime(FMT), todo_id),
                )
            else:
                conn.execute(
                    "UPDATE todos SET status='notified',notified_at=? WHERE id=?",
                    (now.strftime(FMT), todo_id),
                )
