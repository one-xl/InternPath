# CareerPath AI - 职业规划助手

一个智能职业规划工具，通过分析岗位 JD 自动提取技能点，搜索 Bilibili 优质课程，并支持一键同步到本地刷题软件。

## 功能特点

- 🤖 **AI 技能提取**: 使用 LLM 自动分析岗位 JD，提取核心技能和岗位信息
- 🔍 **Bilibili 课程搜索**: 自动搜索相关技能的优质课程
- 📊 **智能排序**: 基于相关度、内容质量和时效性的综合评分算法
- 💾 **数据持久化**: SQLite 数据库存储分析历史和课程信息
- 🚀 **一键刷题**: 自动导出技能包并唤醒本地 C# 刷题软件
- 🎨 **可视化界面**: 基于 Streamlit 的友好用户界面

## 项目结构

```
/workspace/
├── config.py           # 配置文件
├── models.py           # Pydantic 数据模型
├── database.py         # SQLite 数据库模块
├── ai_analyzer.py      # AI 技能提取模块
├── crawler.py          # Bilibili 爬虫模块
├── ranker.py           # 智能排序算法模块
├── practice_app.py     # 刷题软件联动模块
├── service.py          # 核心业务逻辑服务
├── app.py              # Streamlit UI 应用
├── requirements.txt    # Python 依赖
├── .env.example        # 环境变量示例
└── README.md           # 说明文档
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并修改配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# LLM API 配置（支持 DeepSeek 或 OpenAI）
LLM_API_KEY=your_actual_api_key_here
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# 刷题软件路径（Windows 路径）
PRACTICE_APP_PATH=C:\YourAppPath\PracticeApp.exe
```

### 3. 运行应用

```bash
streamlit run app.py
```

应用将在浏览器中自动打开，默认地址：`http://localhost:8501`

## 配置说明

### 修改 API Key 和 LLM 配置

在 [config.py](file:///workspace/config.py) 中可以修改默认配置，或通过环境变量设置：

```python
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "your_api_key_here")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
```

### 修改 C# 刷题软件路径

在 [config.py](file:///workspace/config.py) 中修改：

```python
PRACTICE_APP_PATH: str = os.getenv("PRACTICE_APP_PATH", r"C:\YourAppPath\PracticeApp.exe")
```

或通过环境变量 `PRACTICE_APP_PATH` 设置。

## 核心模块说明

### 1. AI 技能提取模块 ([ai_analyzer.py](file:///workspace/ai_analyzer.py))

调用 LLM API 分析 JD，返回结构化的技能列表、难度评估和岗位简述。

### 2. Bilibili 爬虫模块 ([crawler.py](file:///workspace/crawler.py))

使用 requests + BeautifulSoup 爬取 Bilibili 搜索结果，支持反爬保护（随机 User-Agent、随机延迟）。

### 3. 智能排序算法 ([ranker.py](file:///workspace/ranker.py))

`calculate_rank_score` 函数实现综合评分：

- **相关度 (40%)**: 标题与技能词匹配度
- **内容质量 (40%)**: (收藏+投币+点赞)/播放量
- **时效性 (20%)**: 近 1 年 100 分，每早一年减 20 分

### 4. 数据存储与联动 ([database.py](file:///workspace/database.py), [practice_app.py](file:///workspace/practice_app.py))

- SQLite 持久化分析历史和课程数据
- `invoke_practice_app` 函数导出技能包为 `temp_practice.skillpkg` 并唤醒刷题软件

## 使用示例

1. 在输入框中粘贴岗位 JD
2. 点击「开始分析」按钮
3. 查看分析结果和推荐课程
4. 点击「一键同步至刷题软件」启动本地刷题程序

## 技术栈

- **Backend/Logic**: Python 3.10+
- **UI Framework**: Streamlit
- **AI API**: OpenAI/DeepSeek SDK
- **Crawler**: requests + BeautifulSoup4
- **Database**: SQLite
- **Data Validation**: Pydantic v2

## 注意事项

- 确保已正确配置 LLM API Key
- 刷题软件路径需要根据实际情况修改
- Bilibili 爬虫可能因网站结构变化需要调整
- 建议在 Windows 环境下使用刷题软件联动功能

## License

MIT License
