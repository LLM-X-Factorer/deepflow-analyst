# DeepFlow Analyst

> **企业数据分析智能体** — LLM+X 第二期（DeepFlow）结业项目参考实现
>
> 用自然语言提问，多 Agent 协作生成 SQL、在沙箱中执行、产出带图表的分析报告。
> 面向非技术的业务分析师 / 产品经理 / 运营 / 市场。

🚦 当前版本：`v0.5 · W11 LLMOps + X few-shot RAG + Z stability sampling + W8 HITL + 20-case evaluation gate` —
LangGraph StateGraph 编排的 4-role Agent（Writer / Reviewer / Executor / Insight），
带 intent triage（写操作拦截）+ interrupt-based 意图澄清 HITL；
Writer 的 self-consistency 多数投票（Z）吸收 OpenRouter 路由 noise；
BM25 检索的 few-shot example bank（X）把 Hard 结构性 pattern 的 accuracy 从 20% 抬到 40%；
Langfuse tracing + per-role ModelRouter（W11）打通可观测性和 A/B。
总 accuracy 60%→70%。CI 跑真实 LLM 的 20-case Execution Accuracy 门禁。K8s 在后续周次。

---

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | FastAPI · Uvicorn · SQLAlchemy 2 · Pydantic v2 |
| 前端 | React 19 · Vite 6 · MUI 6 · TypeScript 5 |
| 数据 | PostgreSQL 16 · Chinook 数据集 |
| Agent 编排 | **LangGraph 1.1 StateGraph + MemorySaver** |
| LLM 网关 | OpenRouter · 默认 **`deepseek/deepseek-v3.2`**（见 CLAUDE.md 里的模型选型理由） |
| 包管理 | `uv`（Python 3.11）· `pnpm`（Node） |
| 容器 | Docker · Docker Compose |
| Few-shot RAG | **`rank-bm25`**（BM25 over CJK 字符 unigram+bigram，无 embedding 依赖） |
| 可观测性 | **Langfuse**（可选 · keys 未配则 graceful no-op） + 自研 per-role ModelRouter |
| CI | GitHub Actions（backend lint/type/test · docker build · **evaluation gate**） |

后续周次增量引入：few-shot RAG（W4-5）· MCP/E2B（W7）· Langfuse + ModelRouter（W11）· Kubernetes（W12-13）。

---

## 快速启动

### 1. 准备环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你在 https://openrouter.ai/keys 生成的真实 API Key
```

### 2. 拉取 Chinook 数据集

```bash
bash scripts/fetch-chinook.sh
```

### 3. 一键启动

```bash
docker compose up --build
```

启动后：
- 后端：http://localhost:8090  （`/health` · `/docs` · `POST /api/query`）
- Postgres：`localhost:55433` · user/pass/db 均为 `deepflow`

前端单独起（Vite 自动在 5173/5174/5175 中选第一个空的）：
```bash
cd web && pnpm install && pnpm dev
```

> 端口选择 8090 / 55433 而非默认 8000 / 5432 是为了避开常见本地开发占用。
> 如需调整，改 `docker-compose.yml` 的 `ports` 和 `web/vite.config.ts` 的 `proxy`。

### 4. 本地开发（不用 Docker）

```bash
uv sync                              # 装依赖，自动下载 Python 3.11
uv run uvicorn deepflow_analyst.main:app --reload
```

---

## 项目结构

```
deepflow-analyst/
├── CLAUDE.md                 # 给 Claude Code / 进阶学员的项目指南（决策理由、踩坑清单）
├── src/deepflow_analyst/
│   ├── main.py               # FastAPI app + 多轮 /api/query 协议
│   ├── settings.py           # pydantic-settings（temperature=0 等默认值）
│   ├── llm_client.py         # OpenRouter 薄封装
│   ├── db.py                 # SQLAlchemy engine
│   ├── evaluation.py         # Execution Accuracy scorer + `deepflow-eval` CLI
│   └── agent/
│       ├── pipeline.py       # 4 SQL 角色（generate / review / execute / interpret）
│       └── graph.py          # LangGraph StateGraph + intent triage + HITL interrupt
├── tests/
│   ├── test_*.py             # 37 项单测（pipeline / graph / evaluation / api）
│   └── golden/               # 黄金数据集（20 条 NL→SQL ground truth）
├── web/                      # React 19 + Vite 6 + MUI 6
├── data/seed/                # Chinook SQL（git 忽略，脚本下载 + patch）
├── scripts/fetch-chinook.sh  # 下载 Chinook + sed 剥离 CREATE DATABASE
├── .github/workflows/ci.yml  # 3 job：backend · docker · evaluation gate
├── Dockerfile                # 多阶段（uv builder → slim runtime）
├── docker-compose.yml        # app + postgres
└── pyproject.toml            # uv / ruff / mypy / pytest 配置
```

---

## 评估门禁（Evaluation Gate）

CI 里第三个 job `evaluation` 会在 `pull_request` / `push to main` 时运行：

1. 起一个 PostgreSQL 16 service，灌入 Chinook
2. 跑 `uv run deepflow-eval`——对每条 golden case：生成 SQL → 执行 → 与 ground truth SQL 的执行结果做集合等价比较
3. 计算 **Execution Accuracy**；低于 `EVAL_THRESHOLD`（CI 默认 0.60，本地基线 14/20 = 70%，CI 首轮观察 13/20 = 65%）则 fail
4. 上传 `evaluation_report.md` 为 artifact，并写入 PR 的 Step Summary

阈值随基线自然抬升：每次架构改进（CrewAI / LangGraph / Z 采样 / X RAG）把 accuracy 抬上去或把 noise 压下去后，同步上调 `EVAL_THRESHOLD`，防止回归。

> **Z · stability sampling**（v0.3+）：CI 里 `SAMPLE_SIZE=3` 让 Writer 以 `sample_temperature=0.5` 采样 3 次，各自过 Reviewer 后执行，再按**结果集**多数投票。设计目的是吸收 OpenRouter 上游路由的 ±5pp noise。本地开发默认 `SAMPLE_SIZE=1`（零开销），按需在 `.env` 里覆写。
>
> **X · few-shot RAG**（v0.4+）：`rag_enabled=true`（默认）时，Writer 从 `src/deepflow_analyst/fewshot/examples.jsonl` 的 23 条独立 example 里 BM25 检索 top-K 相似 (question, sql) 对注入 system prompt，给 LLM 提供 hard 结构性 pattern（DISTINCT ON、self-join、多表 join chain）的 precedent。bank 严格独立于 golden dataset（tests 有守门员），`rag_enabled=false` 可做 A/B 对照。总 accuracy 60%→70%，Hard 20%→40%。

### 本地跑评估

```bash
# 前提：docker compose 已起、.env 里有真实 OPENROUTER_API_KEY
uv run deepflow-eval

# 只跑前 3 条做 smoke test
EVAL_LIMIT=3 uv run deepflow-eval

# 把门槛调紧
EVAL_THRESHOLD=0.80 uv run deepflow-eval
```

### 启用 CI 门禁：配置 GitHub Secret

没有 `OPENROUTER_API_KEY` secret 时，CI 会 **graceful skip**（绿但带 warning）。启用门禁：

```bash
gh secret set OPENROUTER_API_KEY -R LLM-X-Factorer/deepflow-analyst
# 粘贴你的 OpenRouter key，回车即可
```

或者去 repo Settings → Secrets and variables → Actions → New repository secret，名字写 `OPENROUTER_API_KEY`。

### 扩充黄金数据集

`tests/golden/golden_dataset.jsonl` 当前有 20 条（6 easy / 9 medium / 5 hard），覆盖 single-table、join、having、top-N、date-filter、anti-join、self-join、DISTINCT ON、multi-join chain 等常见 pattern。W10 教学环节学员继续扩到 50+ 条——这也是 fork 成自己简历项目时最直观的 customization 点。格式说明见 `tests/golden/README.md`。

---

## 14 周 → 项目演进路线

| 周 | 本仓库状态 |
|----|----------|
| W1 | ✅ 项目骨架 · Docker · FastAPI · Postgres · Chinook |
| W2 | 产品画布 · PRD 文档（课程材料侧，非代码） |
| W3 | ✅ 前端 React+MUI · 全栈打通 |
| W4-5 | ⏳ few-shot example bank / 简易 RAG（抬 Hard cases 的 accuracy） |
| W6 | ✅ 首个端到端 Demo（4-role pipeline：Writer / Reviewer / Executor / Insight） |
| W7 | ⏳ MCP · E2B 沙箱 · 外部 API 工具调用 |
| W8 | ✅ **LangGraph StateGraph · MemorySaver · 写操作拦截 · interrupt-based 澄清 HITL** |
| W9 | ⏳ 多轮对话扩展 · 敏感表审核 · PostgresSaver 持久化 |
| W10 | ✅ 20 条 golden dataset · Execution Accuracy · CI 评估门禁（基线 12/20 = 60%） |
| W11 | ✅ **Langfuse 可观测（opt-in）· per-role ModelRouter（writer/reviewer/intent/insight）** · 语义缓存/FinOps 留给学员 |
| W12 | ⏳ Kubernetes · Helm · HPA |
| W13 | ⏳ 蓝绿部署 · 评估阈值门禁卡生产 |
| W14 | ⏳ 商业化 · 定价 · GTM · 路演 |

---

## 如何把它改造成你自己的简历项目

本仓库是**教学参考实现**——骨架不动，换数据就是一个新行业的 AI 产品：

1. 替换 `data/seed/` 下的业务数据（金融 / 医疗 / 电商 / 游戏 / 法律 …）
2. 替换 `src/deepflow_analyst/agent/pipeline.py` 里 `CHINOOK_SCHEMA` 常量为你的业务 schema
   （W4-5 教学里会升级成 Milvus/pgvector 的向量化 schema RAG）
3. 替换 `tests/golden/golden_dataset.jsonl` 为你业务的 20-50 条典型查询 ground truth
4. 调整 `graph.py` 里 `INTENT_SYSTEM_PROMPT` 的写操作/敏感表判定规则

技术骨架（LangGraph 编排 · 4-role Agent · HITL interrupt · Execution Accuracy 评估 · 评估门禁 CI）全部复用。

---

## License

MIT © 2026 LLM+X Course
