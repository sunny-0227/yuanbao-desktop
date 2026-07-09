"""
本地日期时间服务
纯本地计算，无网络请求，直接返回中文自然语言字符串。

支持的 action：
    current_weekday   → 今天是星期几
    current_time      → 现在时间是 HH:MM
    current_date      → 今天是 YYYY年MM月DD日，星期X
    current_datetime  → 今天是 YYYY年MM月DD日，星期X，现在时间是 HH:MM
    tomorrow_weekday  → 明天是星期几
"""

from datetime import datetime, timedelta

_WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


class DateTimeService:
    """
    本地日期时间查询服务。
    所有方法返回中文字符串，不抛异常。
    """

    def query(self, action: str) -> str:
        """
        根据 action 返回对应的日期时间信息。

        参数：
            action: current_weekday / current_time / current_date /
                    current_datetime / tomorrow_weekday

        返回：中文自然语言字符串
        """
        try:
            now = datetime.now()
            if action == "current_weekday":
                return self.current_weekday(now)
            if action == "current_time":
                return self.current_time(now)
            if action == "current_date":
                return self.current_date(now)
            if action == "current_datetime":
                return self.current_datetime(now)
            if action == "tomorrow_weekday":
                return self.tomorrow_weekday(now)
            return f"未知日期时间操作：{action}"
        except Exception as e:
            return f"⚠️ 日期时间查询出错：{e}"

    # ── 各类查询 ──────────────────────────────────────────────

    def current_weekday(self, now: datetime) -> str:
        """今天是星期几"""
        return f"今天是{_WEEKDAY_CN[now.weekday()]}。"

    def current_time(self, now: datetime) -> str:
        """现在时间是 HH:MM"""
        return f"现在时间是 {now.strftime('%H:%M')}。"

    def current_date(self, now: datetime) -> str:
        """今天是 YYYY年MM月DD日，星期X"""
        return (
            f"今天是 {now.year}年{now.month:02d}月{now.day:02d}日，"
            f"{_WEEKDAY_CN[now.weekday()]}。"
        )

    def current_datetime(self, now: datetime) -> str:
        """今天是 YYYY年MM月DD日，星期X，现在时间是 HH:MM"""
        return (
            f"今天是 {now.year}年{now.month:02d}月{now.day:02d}日，"
            f"{_WEEKDAY_CN[now.weekday()]}，"
            f"现在时间是 {now.strftime('%H:%M')}。"
        )

    def tomorrow_weekday(self, now: datetime) -> str:
        """明天是星期几"""
        tomorrow = now + timedelta(days=1)
        return f"明天是{_WEEKDAY_CN[tomorrow.weekday()]}。"
