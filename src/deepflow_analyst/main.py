import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent, db
from .settings import settings

app = FastAPI(
    title="DeepFlow Analyst",
    description="Enterprise Data Analyst Agent — LLM+X Season 2 Capstone",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5175", "http://localhost:3000"],
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
    question: str | None = None
    thread_id: str | None = None
    resume_input: str | None = None


class QueryResponse(BaseModel):
    status: str
    thread_id: str
    answer: str = ""
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    row_count: int | None = None
    clarification_question: str | None = None
    error: str | None = None


@app.post("/api/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    try:
        result = await agent.run(
            question=req.question,
            thread_id=req.thread_id,
            resume_input=req.resume_input,
        )
        return QueryResponse(
            status=result.status,
            thread_id=result.thread_id,
            answer=result.answer,
            sql=result.sql,
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
            clarification_question=result.clarification_question,
            error=result.error,
        )
    except Exception as e:
        return QueryResponse(
            status="error",
            thread_id=req.thread_id or str(uuid.uuid4()),
            answer="请求失败",
            error=f"{type(e).__name__}: {e}",
        )
