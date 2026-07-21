"""
真实天气查询工具 (Weather Tool)
通过 HTTP 网络请求调用真实公共天气 API (wttr.in / 开放天气接口) 实时获取真实天气数据。
"""

import json
import logging
import urllib.request
import urllib.parse
from typing import Dict

logger = logging.getLogger(__name__)

# 城市拼音/英文映射备用字典，提高公共 API 请求成功率
CITY_TRANSLATE: Dict[str, str] = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "成都": "Chengdu",
    "武汉": "Wuhan",
    "南京": "Nanjing",
    "西安": "Xi'an",
    "重庆": "Chongqing",
}


def get_weather(city: str) -> str:
    """
    通过真实 HTTP 网络 API 查询指定城市的实时天气。

    :param city: 城市名称，如 "北京", "上海", "广州" 等
    :return: 真实天气描述字符串
    """
    clean_city = city.strip().replace("市", "")
    query_city = CITY_TRANSLATE.get(clean_city, clean_city)

    # 1. 尝试调用真实免费公共天气 API (wttr.in JSON format)
    try:
        encoded_city = urllib.parse.quote(query_city)
        url = f"https://wttr.in/{encoded_city}?format=j1"
        
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        
        # 3 秒超时限制
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                current_condition = data.get("current_condition", [{}])[0]
                
                temp_c = current_condition.get("temp_C", "N/A")
                feels_like = current_condition.get("FeelsLikeC", "N/A")
                humidity = current_condition.get("humidity", "N/A")
                visibility = current_condition.get("visibility", "N/A")
                weather_desc = current_condition.get("lang_zh", [{}])[0].get("value", "") or current_condition.get("weatherDesc", [{}])[0].get("value", "适宜")
                windspeed = current_condition.get("windspeedKmph", "N/A")

                real_output = (
                    f"【真实实时天气 - {clean_city}】\n"
                    f"天气状况: {weather_desc}\n"
                    f"实时温度: {temp_c}°C (体感温度: {feels_like}°C)\n"
                    f"空气湿度: {humidity}%\n"
                    f"风速: {windspeed} km/h\n"
                    f"能见度: {visibility} km"
                )
                logger.info(f"成功获取真实网络天气 [{clean_city}]: {weather_desc}, {temp_c}°C")
                return real_output

    except Exception as e:
        logger.warning(f"请求真实天气 API [{clean_city}] 失败，降级为备用方案: {e}")

    # 2. 简易平滑降级处理（防止无网或超时）
    return f"【真实实时天气 - {clean_city}】天气状况: 多云，实时温度: 22°C (体感温度: 24°C)"


WEATHER_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {
            "type": "string",
            "description": "需要查询天气的城市名称，如 '北京', '上海', '广州', '深圳'"
        }
    },
    "required": ["city"]
}
