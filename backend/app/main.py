from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.runtime import get_creative_agent
from app.api.deps import ensure_database_ready
from app.api.routes import router

app = FastAPI(title="Commerce Creative Agent API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    """Prepare local development storage for API requests."""

    ensure_database_ready()
    # main.py 是唯一装配点，API 和应用用例都不创建 LangGraph 基础设施。
    app.state.creative_agent = get_creative_agent()
