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
EVAS_TEXT_LLM_BASE_URL=https://api.openai.com/v1
EVAS_TEXT_LLM_API_KEY=...
EVAS_TEXT_LLM_MODEL=...
EVAS_TEXT_LLM_TIMEOUT_SECONDS=45
EVAS_MULTIMODAL_LLM_BASE_URL=https://api.openai.com/v1
EVAS_MULTIMODAL_LLM_API_KEY=...
EVAS_MULTIMODAL_LLM_MODEL=...
EVAS_MULTIMODAL_LLM_TIMEOUT_SECONDS=45
EVAS_LANGGRAPH_CHECKPOINT_PATH=var/creative_agent_checkpoints.sqlite3
EVAS_ASSET_STORAGE_PATH=var/assets
EVAS_ASSET_MAX_BYTES=10485760
EVAS_ASSET_MAX_FILES_PER_PROJECT=5
EVAS_ASSET_MAX_IMAGE_PIXELS=25000000
```

未配置模型时使用本地确定性方案。上传只接受可完整解码的 JPEG、PNG 和 WebP。
配置 `EVAS_MULTIMODAL_LLM_MODEL` 后，商品理解节点会把已上传商品图以 data URL
发送给 OpenAI-compatible 多模态模型。创意脚本和语义审核使用 `EVAS_TEXT_LLM_*`
配置；两组配置互不兜底，避免把文本模型误用于图片理解。

## Postman 调用

创建 CreativeRun 时一次性提交商品资料和商品图片，不再单独上传素材或单独保存商品资料。

```text
POST http://127.0.0.1:8000/api/v1/projects/{project_id}/creative-runs
Body: form-data

campaign_goal          Text  本次营销目标
product_name           Text  商品名称
selling_points_text    Text  已确认卖点
target_audience_text   Text  目标人群
brand_tone             Text  品牌语气
forbidden_words_text   Text  必须避免的表达
product_images         File  商品图片，可重复添加多张
```

如果图片校验、模型调用或生成流程失败，本次请求会直接失败；用户重新提交同一个
form-data 请求即可。

## 检查

```bash
uv run ruff check app migrations tests
uv run pytest -q
```
