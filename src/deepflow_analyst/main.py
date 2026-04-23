from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent, db
from .settings import settings

app = FastAPI(
    title="DeepFlow Analyst",
    description="Enterprise Data Analyst Agent — LLM+X Season 2 Capstone",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "env": settings.app_env,
        "db": "ok" if db.ping() else "down",
    }


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    status: str = "ok"
    answer: str
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    row_count: int | None = None
    error: str | None = None


@app.post("/api/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    try:
        result = await agent.run(req.question)
        return QueryResponse(
            status="ok",
            answer=result.answer,
            sql=result.sql,
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
        )
    except Exception as e:
        return QueryResponse(
            status="error",
            answer="抱歉，查询失败。请查看 error 字段，或联系运维。",
            error=f"{type(e).__name__}: {e}",
        )
