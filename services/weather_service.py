"""Open-Meteo 免密钥天气查询，城市重名时返回候选而非猜测。"""

import asyncio

import httpx


async def weather(city, cancel):
    async with httpx.AsyncClient(timeout=10) as client:

        async def request():
            response = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 5, "language": "zh"},
            )
            response.raise_for_status()
            matches = response.json().get("results", [])
            if not matches:
                raise ValueError("没有找到这个城市，请试用城市拼音或英文名")
            if len(matches) > 1:
                china = [r for r in matches if r.get("country_code") == "CN"]
                if len(china) == 1:
                    matches = china
                else:
                    raise ValueError(
                        "存在同名城市，请填写更完整的名称："
                        + "、".join(r["name"] + " " + r.get("admin1", "") for r in matches[:3])
                    )
            place = matches[0]
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "timezone": "auto",
                },
            )
            response.raise_for_status()
            current = response.json()["current"]
            return f"{place['name']} · {current['time']}\n气温 {current['temperature_2m']}°C，湿度 {current['relative_humidity_2m']}%，风速 {current['wind_speed_10m']} km/h。\n数据：Open-Meteo"

        task = asyncio.create_task(request())
        while not task.done():
            if cancel.is_set():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                return None
            await asyncio.sleep(0.05)
        return await task
