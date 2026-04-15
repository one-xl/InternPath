import os
import json
import requests
from config import Config

# 测试豆包 API 连接
print("测试豆包 API 连接...")
print(f"API Key: {Config.LLM_API_KEY[:10]}...")
print(f"Base URL: {Config.LLM_BASE_URL}")
print(f"Model: {Config.LLM_MODEL}")

# 使用 requests 直接测试
url = f"{Config.LLM_BASE_URL}/chat/completions"
headers = {
    "Authorization": f"Bearer {Config.LLM_API_KEY}",
    "Content-Type": "application/json"
}
data = {
    "model": Config.LLM_MODEL,
    "messages": [
        {"role": "user", "content": "你好，测试连接"}
    ],
    "temperature": 0.3
}

try:
    response = requests.post(url, headers=headers, json=data)
    print(f"\n响应状态码: {response.status_code}")
    print(f"响应内容: {response.json()}")
    
    if response.status_code == 200:
        print("\n✅ 连接成功！")
        print(f"响应: {response.json()['choices'][0]['message']['content']}")
    else:
        print("\n❌ 连接失败")
        
except Exception as e:
    print(f"\n❌ 连接失败: {str(e)}")
