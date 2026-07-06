# InternPath 中文说明

InternPath 是一个个人求职工作台。主路径是：

1. 输入目标岗位 JD。
2. 选择或粘贴个人材料。
3. 生成投递决策。
4. 查看简历改造建议。
5. 按需展开学习路线、刷题建议和专家调试信息。

前端已经彻底切换为 `React + Vite + TypeScript`，后端为 `FastAPI`。

## 启动

```powershell
.\start_internpath.cmd
```

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8787`
- 增强校验服务：`http://127.0.0.1:8000`

首次运行前需要安装前端依赖：

```powershell
cd frontend
npm install
cd ..
```

## 测试

```powershell
npm run doctor
npm run agent:compile
npm run frontend:build
npm run agent:test

.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

`npm run doctor` 会输出 JSON 格式的本地工具链检查结果，覆盖 Python/Node/npm、关键目录、环境变量、PostgreSQL/Redis 连通性、端口占用和源码扫描计数，方便人和 Agent 快速判断缺什么。
