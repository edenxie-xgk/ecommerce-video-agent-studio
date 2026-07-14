# Commerce Creative Agent

面向电商内容团队的短视频创意决策工作台。用户提供商品事实、素材和营销目标，
系统在启动前校验必要资料；Agent 负责生成三套 15 秒方案、执行自动质量预检，
并把通过结果交给人工审核。需要用户决定“是否继续”或提出修改意见的动作，
由生成结果之后的人工确认节点承载。

## 快速开始

```bash
cd backend
uv run python scripts/init_database.py
uv run uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

未配置模型时使用本地确定性方案；模型、数据库和图片存储配置见
[backend/README.md](backend/README.md)。

## 文档

- [产品范围](docs/PRODUCT.md)：目标用户、核心价值、当前边界和成功指标。
- [技术架构](docs/ARCHITECTURE.md)：模块职责、LangGraph 流程和状态持久化。
- [工程规范](docs/HERMES_ENGINEERING.md)：实现原则、注释要求和变更检查项。

## 目录

- `backend/`：FastAPI、SQLModel、Alembic 和 LangGraph Agent。
- `frontend/`：Vue 3、Pinia 和 Naive UI 工作台。
