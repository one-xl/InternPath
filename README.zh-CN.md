# InternPath

[English README](README.md)

InternPath 是一个基于 Streamlit 的岗位 JD 分析工具，面向实习和求职准备场景。它可以调用大模型从 JD 中提取技能点、难度和岗位摘要，搜索并推荐匹配的 Bilibili 课程，保存分析历史，并为本地 AiSmartDrill 客户端生成启动载荷。

## 功能

- 分析岗位 JD，提取技能、难度和岗位概述
- 保存分析历史，并支持自定义历史记录名称
- 支持“添加分析”草稿流程，分析后手动保存到历史记录
- 根据提取的技能搜索并排序 Bilibili 课程
- 使用 SQLite 在本地持久化分析记录和课程结果
- 生成 `aismartdrill://` 启动链接或本地技能包文件
- 通过访问密码保护网页入口

## 技术栈

- Python
- Streamlit
- OpenAI 兼容 SDK
- HTTPX
- Pydantic v2
- SQLite

## 项目结构

```text
app.py                  Streamlit 页面
service.py              业务服务层
ai_analyzer.py          基于 LLM 的 JD 分析
crawler_api.py          Bilibili 课程搜索
ranker.py               课程排序逻辑
database.py             SQLite 持久化
models.py               Pydantic 数据模型
practice_app.py         AiSmartDrill 载荷和导出辅助
config.py               基于环境变量的配置
deploy/                 本地和服务器部署脚本
```

## 环境要求

- Python 3.9+
- 与 `LLM_BASE_URL` 兼容的大模型 API Key

## 快速开始

1. 安装依赖。

```bash
pip install -r requirements.txt
```

2. 从示例文件创建 `.env`，再填入你自己的配置。

```bash
cp .env.example .env
```

示例：

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
APP_PASSWORD=change_me
PRACTICE_APP_PATH=C:\Path\To\AiSmartDrill.App.exe
```

3. 启动应用。

```bash
streamlit run app.py
```

默认本地地址：

`http://127.0.0.1:8501`

## 配置项

核心环境变量：

- `LLM_API_KEY`：必填
- `LLM_BASE_URL`：可选，默认 `https://api.deepseek.com`
- `LLM_MODEL`：可选，默认 `deepseek-chat`
- `LLM_TIMEOUT`：可选，请求超时时间，单位秒
- `APP_PASSWORD`：适合开发环境或私有部署的明文访问密码
- `APP_PASSWORD_HASH`：更适合正式环境的 PBKDF2 哈希密码
- `PRACTICE_APP_PATH`：本地 Windows 机器上的 AiSmartDrill 可执行文件路径

如果 `APP_PASSWORD` 和 `APP_PASSWORD_HASH` 都为空，登录页将无法通过校验，直到你配置其中一个值。

## 运行模式

### Windows 本地运行

使用辅助脚本：

```powershell
.\deploy\run_local.ps1
```

详见 [deploy/LOCAL_WINDOWS.md](deploy/LOCAL_WINDOWS.md)。

### Linux / Debian 服务器运行

服务器部署使用 `requirements.server.txt` 和 `deploy/server_install.sh`。

详见 [deploy/DEPLOY_DEBIAN.md](deploy/DEPLOY_DEBIAN.md)。

## 测试

当前仓库中的测试主要覆盖 API 集成的部分逻辑以及技能包生成逻辑：

```bash
pytest
```

## 隐私与仓库清洁

这个仓库已经按公开托管做过基础脱敏：

- `.env` 不会进入 Git
- SQLite 数据库文件被忽略
- `.vscode/` 等本地编辑器目录被忽略
- 部署脚本中不再写死服务器地址
- 示例文件只保留占位用的 API Key、密码和可执行文件路径

在你继续推送自己的修改前，仍然应该检查是否把真实 API Key、密码、私有主机名或本机路径写进了已跟踪文件。
