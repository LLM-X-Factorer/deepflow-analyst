# DeepFlow Analyst

> **企业数据分析智能体** — LLM+X 第二期（DeepFlow）结业项目参考实现
>
> 用自然语言提问，多 Agent 协作生成 SQL、在沙箱中执行、产出带图表的分析报告。
> 面向非技术的业务分析师 / 产品经理 / 运营 / 市场。

🚦 **当前版本：`v0.5`** · Execution Accuracy 本地 14/20 = **70%**（baseline 12/20 = 60%）

核心能力：

- **LangGraph 4-role Agent** — Writer / Reviewer / Executor / Insight，按 StateGraph 声明边串联
- **HITL（W8）** — intent triage 拦截写操作；ambiguous 意图走 `interrupt()` → 等用户澄清 → resume
- **Z · stability sampling** — Writer 采样 K 次 × Reviewer 规整 × 结果集多数投票，吸收 OpenRouter ±5pp 路由 noise
- **X · few-shot RAG** — 23 条独立 example bank × BM25 字符 n-gram 检索 × 注入 Writer system prompt，Hard 结构性 pattern 的 accuracy 20%→40%
- **LLMOps（W11）** — Langfuse tracing（opt-in · keys 未配自动 no-op）+ per-role ModelRouter（writer/reviewer/intent/insight 各自可覆写 model）
- **Evaluation gate** — CI 里 20-case golden dataset 跑真实 LLM，accuracy 低于阈值就 fail

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

下一步：MCP/E2B 沙箱（W7）· Kubernetes 部署（W12-13）· 商业化 + 路演（W14）。完整对照见下方 14 周路线。

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
├── CLAUDE.md                         # 给 Claude Code / 进阶学员的项目指南（决策理由、踩坑清单）
├── src/deepflow_analyst/
│   ├── main.py                       # FastAPI app + 多轮 /api/query 协议
│   ├── settings.py                   # pydantic-settings（temperature=0 / Z / X / W11 的所有 env 开关）
│   ├── llm_client.py                 # OpenRouter 薄封装 + 可选 Langfuse tracing wrapper
│   ├── model_router.py               # W11 · resolve_model(role) 按角色取模型，fallback default_model
│   ├── retrieval.py                  # X · BM25 few-shot bank（CJK 字符 unigram+bigram）
│   ├── fewshot/
│   │   └── examples.jsonl            # X · 23 条独立 example（打进 wheel，禁止和 golden 重叠）
│   ├── db.py                         # SQLAlchemy engine
│   ├── evaluation.py                 # Execution Accuracy scorer + `deepflow-eval` CLI
│   └── agent/
│       ├── pipeline.py               # 4 SQL 角色 + Z 采样投票 + X RAG 注入
│       └── graph.py                  # LangGraph StateGraph + intent triage + HITL interrupt
├── tests/                            # 58 项单测（pipeline / graph / retrieval / router / evaluation / api）
│   └── golden/                       # 黄金数据集（20 条 NL→SQL ground truth）
├── web/                              # React 19 + Vite 6 + MUI 6
├── data/seed/                        # Chinook SQL（git 忽略，脚本下载 + patch）
├── scripts/fetch-chinook.sh          # 下载 Chinook + sed 剥离 CREATE DATABASE
├── .github/workflows/ci.yml          # 3 job：backend · docker · evaluation gate
├── Dockerfile                        # 多阶段（uv builder → slim runtime）
├── docker-compose.yml                # app + postgres
└── pyproject.toml                    # uv / ruff / mypy / pytest 配置
```

---

## 核心特性解读

### Z · Stability Sampling

Writer 在 `sample_temperature=0.5` 下采样 `SAMPLE_SIZE` 次，每个候选独立过 Reviewer + 真 DB 执行，再按**结果集多重集**（非 SQL 文本）做多数投票。设计目的是吸收 OpenRouter 上游路由的 ±5pp noise——本地 temp=0 已是稳态，所以 Z 不抬 ceiling、只压 noise。默认 `SAMPLE_SIZE=1`（本地零开销），CI 覆写成 `3`。

### X · Few-shot RAG

Writer 从 `src/deepflow_analyst/fewshot/examples.jsonl` 的 23 条独立 example bank 里用 BM25 检索 top-K 相似 (question, sql) 对，注入 system prompt 作为 precedent。tokenizer 是 CJK 字符 unigram+bigram，无 embedding / torch 依赖。**bank 严格独立于 golden dataset**——`tests/test_retrieval.py::test_bank_independent_of_golden_dataset` 是守门员，任何重叠都是把 ground truth 作弊注入 eval。默认 `RAG_ENABLED=true`；`false` 可做 A/B 对照。贡献：本地 60%→70%，Hard 20%→40%。

### W11 · LLMOps

两件事：

- **Langfuse tracing（opt-in）**：`LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` 同时配齐才启用，否则 `llm_client` 走 plain openai 路径，零 overhead。启用后每次 `chat(role=...)` 在 Langfuse UI 里按 writer / reviewer / intent / insight 分组。
- **Per-role ModelRouter**：`WRITER_MODEL` / `REVIEWER_MODEL` / `INTENT_MODEL` / `INSIGHT_MODEL` 各自可覆写；为空 fallback 到 `DEFAULT_MODEL`。**有意不做自动复杂度分类**——任何 model fanout 必须先用 `deepflow-eval` 验证。

---

## 评估门禁（Evaluation Gate）

CI 里第三个 job `evaluation` 会在 `pull_request` / `push to main` 时运行：

1. 起一个 PostgreSQL 16 service，灌入 Chinook
2. 跑 `uv run deepflow-eval` —— 对每条 golden case：生成 SQL → 执行 → 与 ground truth SQL 的执行结果做集合等价比较
3. 计算 **Execution Accuracy**；低于 `EVAL_THRESHOLD` 就 fail
4. 上传 `evaluation_report.md` 为 artifact，并写入 PR 的 Step Summary

当前阈值 `EVAL_THRESHOLD=0.60`，基于实测 CI 波动范围确定：

| 环境 | 最近观察（4 次 CI） | 备注 |
|----|---|----|
| 本地 RAG + Z=3 | 14/20 = **70%**（稳定复现） | 生产默认配置 |
| CI RAG + Z=3 | [60%, 65%, 65%, 70%]，均值 65% | OpenRouter 上游路由吃掉一部分本地 gain |

阈值按 **CI 观察值 - 5pp buffer** 定，不跟本地 gain 走——这是 v0.4 X 落地时学到的（当时一度把阈值抬到 0.65，下一次 CI 就跑到 60%，所以 revert 回 0.60）。每次架构改进把 CI 观察值稳定抬上去后，同步上调阈值。

### 本地跑评估

```bash
# 前提：docker compose 已起、.env 里有真实 OPENROUTER_API_KEY
uv run deepflow-eval                       # 默认 · RAG 开 · N=1 · 最省 token
SAMPLE_SIZE=3 uv run deepflow-eval         # Z · 多数投票（CI 走这条）
RAG_ENABLED=false uv run deepflow-eval     # 关 X · 对照组
EVAL_LIMIT=3 uv run deepflow-eval          # smoke test（前 3 条）
EVAL_THRESHOLD=0.80 uv run deepflow-eval   # 紧阈值试试水
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
| W4-5 | ✅ **X · few-shot RAG**（BM25 · 23 条独立 example bank · Hard 20%→40%，总 60%→70%）|
| W6 | ✅ 首个端到端 Demo（4-role pipeline：Writer / Reviewer / Executor / Insight） |
| W7 | ⏳ MCP · E2B 沙箱 · 外部 API 工具调用 |
| W8 | ✅ **LangGraph StateGraph · MemorySaver · 写操作拦截 · interrupt-based 澄清 HITL** |
| W9 | ⏳ 多轮对话扩展 · 敏感表审核 · PostgresSaver 持久化 |
| W10 | ✅ 20 条 golden dataset · Execution Accuracy · CI 评估门禁（基线 12/20 = 60%，v0.5 已抬至 14/20 = 70%）|
| +Z | ✅ **Z · stability sampling**（多数投票消 CI noise，使 threshold 从 0.55 抬到 0.60 稳定）|
| W11 | ✅ **Langfuse tracing（opt-in）· per-role ModelRouter** · 语义缓存/FinOps 留给学员 |
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
