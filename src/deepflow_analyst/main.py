from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
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
    answer: str
    status: str = "not_implemented"


@app.post("/api/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    return QueryResponse(
        answer=f"Received: {req.question!r}. Agent pipeline lands in W6.",
        status="not_implemented",
    )
