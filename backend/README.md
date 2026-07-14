# Backend

FastAPI 服务，负责项目、商品资料、素材、CreativeRun 和 LangGraph checkpoint。
完整模块与状态设计见 [技术架构](../docs/ARCHITECTURE.md)。

## 启动

```bash
uv run python scripts/init_database.py
uv run uvicorn app.main:app --reload
```

业务数据库默认位于 `var/app.sqlite3`，LangGraph checkpoint 默认位于
`var/creative_agent_checkpoints.sqlite3`，通过校验的商品图片默认保存在 `var/assets/`。

## 配置

环境变量使用 `EVAS_` 前缀：

```bash
EVAS_DATABASE_URL=postgresql+psycopg://...
EVAS_LLM_BASE_URL=https://api.openai.com/v1
EVAS_LLM_API_KEY=...
EVAS_LLM_MODEL=...
EVAS_LLM_TIMEOUT_SECONDS=45
EVAS_LANGGRAPH_CHECKPOINT_PATH=var/creative_agent_checkpoints.sqlite3
EVAS_ASSET_STORAGE_PATH=var/assets
EVAS_ASSET_MAX_BYTES=10485760
EVAS_ASSET_MAX_FILES_PER_PROJECT=5
EVAS_ASSET_MAX_IMAGE_PIXELS=25000000
```

未配置模型时使用本地确定性方案。上传只接受可完整解码的 JPEG、PNG 和 WebP；
当前 Agent 使用经过验证的图片引用规划镜头，但不会读取像素内容或给出视觉真实性结论。

## 检查

```bash
uv run ruff check app migrations tests
uv run pytest -q
```
