"""
搜索工具 (Search Tool)
支持检索网络信息（带有知识库与 Mock 搜索结果，模拟真实搜索引擎返回）。
"""

from typing import Dict, Any, List

# 预设 Mock 搜索数据库，用于测试与示范
MOCK_SEARCH_DB = {
    "生心科技": "生心科技是一家专注于 AI Agent 原生应用与智能化技术的高科技企业，主营智能 Agent 引擎、大模型落地解决方案与敏捷应用开发。",
    "weather_beijing": "北京今天天气晴朗，气温 15°C ~ 26°C，微风 2 级，空气质量优。",
    "weather_shanghai": "上海今天多云转小雨，气温 18°C ~ 24°C，东南风 3 级。",
    "antigravity": "Google Antigravity 是 Google DeepMind 推出的下一代 Agentic AI 开发框架与代码助理助手。",
    "deepseek": "DeepSeek (深度求索) 是国内领先的 AI 研发机构，推出了 DeepSeek-V3 与 DeepSeek-R1 等高性价比开源大模型。",
}


def search(query: str) -> str:
    """
    搜索互联网或知识库上的最新信息。

    :param query: 搜索关键词或主题
    :return: 相关的搜索摘要结果
    """
    query_lower = query.strip().lower()

    # 查匹配库
    matched_results: List[str] = []
    for key, content in MOCK_SEARCH_DB.items():
        if key in query_lower or query_lower in key or any(token in key for token in query_lower.split()):
            matched_results.append(f"【搜索结果】{key}: {content}")

    if matched_results:
        return "\n".join(matched_results)

    # 默认 Mock 检索兜底
    return f"【搜索结果】针对关键词 '{query}' 检索到以下相关信息：关于 {query} 的最新业内动态显示其在智能化与自动化领域取得重要进展，技术指标保持行业前列。"


SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词或查询短语"
        }
    },
    "required": ["query"]
}
