# DeepFlow Analyst — Project Guide for Claude

> 读者：在此仓库工作的 Claude Code 助手、fork 此项目做简历的学员。
>
> 简介：企业数据分析智能体，LLM+X 第二期「DeepFlow」结业项目的 reference
> implementation。用户用自然语言问数据库，多 Agent 协作生成 SQL、在安全
> 边界内执行、产出带图表/解读的报告。

---

## 目标角色

| 角色 | 读 CLAUDE.md 的目的 |
|------|------|
| **未来的 Claude** | 避免重走已经讨论过的技术弯路；理解当前基线、瓶颈、下一步 |
| **学员 fork 后** | 知道哪些决策已经冻结、哪些可以自由改 |

---

## 技术栈（已冻结的决策，不要 re-argue）

| 层 | 选型 | 为什么不换 |
|----|------|----------|
| Python 包管理 | **uv**（非 PDM/Poetry） | 2026 主流、Rust 速度、学员一行 `uv sync` 能跑 |
| Python 运行时 | **3.11**（锁 `>=3.11,<3.13`） | LangChain/LangGraph/CrewAI 生态在 3.11 最稳 |
| 后端 | FastAPI + Uvicorn + SQLAlchemy + pydantic v2 | 课程基线 |
| 前端 | React 19 + Vite 6 + MUI 6 + TypeScript 5 | |
| 数据库 | PostgreSQL 16（Chinook 音乐商店种子数据） | |
| Agent 编排 | **LangGraph 1.1 StateGraph + MemorySaver** | 见"为什么不用 CrewAI" |
| LLM 网关 | **OpenRouter**（统一 key、多 provider 切换） | |
| 默认模型 | **deepseek/deepseek-v3.2** | 见"为什么不用 Claude/GPT" |
| 评估 | 自研 `deepflow-eval` CLI + Execution Accuracy | 避免 DeepEval/Ragas 的额外依赖 |
| Retrieval (X) | `rank-bm25`（纯 Python，无 torch/embedding 依赖） | 见"为什么 X 用 BM25" |
| 容器 | Docker + Docker Compose | |
| CI | GitHub Actions（3 job：backend、docker、evaluation gate） | |

### 为什么不用 CrewAI 框架

CrewAI 对一个**固定 4 步流水线**是 overkill——它的 planner agent 会额外烧 token 且可能改错正确 SQL。我们手写 4-role 架构（Writer / Reviewer / Executor / Insight），用 LangGraph StateGraph 声明边即可。教学等价。

### 为什么不用 Claude 或 GPT 作为默认模型

2026-04 测试：用户 OpenRouter 账号用 `anthropic/claude-haiku-4.5` 和 `openai/gpt-4o-mini` 都会 **403 provider-ToS**（即使 `gh credits` 显示余额充足）。这是 OpenRouter 对某些地区/账号的 provider-level 限制。`deepseek/deepseek-v3.2` 对所有地区开放，且是当前定价/质量最佳选。**不要自作主张把默认模型换回 Claude/GPT**。

### 为什么 temperature = 0

未固定温度时本地跑 4/7 而 CI 跑 5/7 → 14pp 随机漂移让每个改动都无法 measure。pinned `settings.default_temperature = 0.0` 后两次 back-to-back eval 产出一致 57.1%，此后所有改动都可以用数据对比。**不要把它改回 >0**，除非 W11 教学里有意对比 temperature 对解读 naturalness 的影响（且只针对 Insight agent，不影响 SQL Writer）。

### 为什么 X（RAG）用 BM25 字符 n-gram 而不是 embedding

- 不依赖外部 embedding API（OpenRouter 主打 chat completions，embeddings 不通用）
- 不引入 sentence-transformers + torch 这种 GB 级依赖
- 23 条 short-question 小 corpus 上 BM25 的召回足够——字符 unigram+bigram 在中文上比按词分词更省依赖且对短 query 更 robust
- 教学递进清晰：W4-5 起步用 BM25，W11 升级成 pgvector + embedding 当作对比示例，跟「先稳定基线再量改进」一脉相承

### Example bank 和 golden dataset 的严格隔离

`src/deepflow_analyst/fewshot/examples.jsonl`（23 条，打包进 wheel）**绝对不能**和 `tests/golden/golden_dataset.jsonl` 的 `question` 字段有重叠——否则 RAG 会把 golden 的 ground truth SQL 注入 Writer prompt，让 eval 分数虚高。`tests/test_retrieval.py::test_bank_independent_of_golden_dataset` 是这个不变式的守门员，回归到这条要立刻改不要放过。

### 为什么 Z 用 SAMPLE_TEMPERATURE=0.5 而 default_temperature 还是 0

两个温度管两件事：
- `default_temperature = 0.0` 管单 shot + Reviewer + Insight，用于**可复现**
- `sample_temperature = 0.5` 只在 `SAMPLE_SIZE > 1` 时给 Writer 用，用于**多样性**

Self-consistency 要求 K 个候选 diverge 才能 vote 出 signal；如果都用 temp=0 就是 K 份一样的答案，投票没意义。每个候选被 Reviewer（temp=0）规整后再执行、按**结果集**（不是 SQL 文本）多数投票——surface-form 差异不扣分。

---

## 本地端口映射（避开常见本地开发占用）

| 服务 | 容器端口 | 宿主端口 |
|-----|---------|---------|
| App (FastAPI) | 8000 | **8090** |
| PostgreSQL | 5432 | **55433** |
| Frontend (Vite) | 5173 | **5175**（前两个会被占用就 fallback） |

---

## 开发 Workflow

### 首次启动
```bash
# 1. 填入 OpenRouter Key（⚠️ 不要 commit）
cp .env.example .env
#  手动编辑 .env 的 OPENROUTER_API_KEY

# 2. 拉 Chinook 种子
bash scripts/fetch-chinook.sh

# 3. 一键起全栈
docker compose up -d --build

# 4. 前端
cd web && pnpm install && pnpm dev
```

### 本地跑评估
```bash
uv run deepflow-eval                      # 全量（20 cases · 单次采样 · 最省 token）
EVAL_LIMIT=3 uv run deepflow-eval         # smoke test
EVAL_THRESHOLD=0.70 uv run deepflow-eval  # 紧阈值
SAMPLE_SIZE=3 uv run deepflow-eval        # Z · 多数投票（CI 走这条路径）
RAG_ENABLED=false uv run deepflow-eval    # 关 X · 做 RAG A/B 对照
```

### 换依赖后必须 `--build`
```bash
# ❌ 错：docker compose restart app   # 不会重装新依赖，也不会重读 .env
# ✅ 对：docker compose up -d --build app
# ✅ 或者 env_file 变了但没装新依赖：docker compose up -d --force-recreate app
```

---

## 踩过的坑（已修、请勿再犯）

1. **`docker compose restart` 不重载 `env_file`**——它只重启进程，容器环境变量还是 up 时 bake 的。改 `.env` 后要用 `up -d --force-recreate`（或 `--build` 如果 pyproject 也变了）。
2. **`.dockerignore` 不要屏蔽 `README.md`**——`hatchling` 构建时读取它作为 package metadata，否则 image build 失败。
3. **Chinook 上游 SQL 会 `CREATE DATABASE chinook; \c chinook`**，把所有表建到独立的 chinook db。`scripts/fetch-chinook.sh` 里有 sed patch 剥除这两行，让表建到 POSTGRES_DB (`deepflow`) 里。
4. **Chinook 数据是 2021-2025，不是 2012 年**——给 date-filter 类用例写 SQL 时要用真实年份。
5. **LLM 响应默认非 deterministic**——temperature=0 也不完美（upstream provider routing noise）。CI 比本地 ±5pp 是正常的。
6. **Vite 5173 / 5174 可能被其他项目占**——`package.json` 不锁端口，Vite 会自动 fallback 到 5175+，但 `vite.config.ts` 的 proxy 目标是 backend port 8090。

---

## 架构（5 秒速览）

```
question → intent(LLM)
            ├── write      → write_rejected → END
            ├── ambiguous  → clarify(interrupt → resume) → intent
            └── read       → writer(LLM) → reviewer(LLM)
                              → executor(SQL on PG) → insight(LLM) → END
```

每次 LLM→LLM 过渡都 **validate_sql**，防止 reviewer 或 resume input 注入写操作。状态用 `MemorySaver` 按 `thread_id` 隔离（W8 教学换成 `PostgresSaver`）。

### 关键模块

| 文件 | 职责 |
|------|------|
| `src/deepflow_analyst/agent/graph.py` | LangGraph 拓扑 + HITL 节点 + 公开 `run()` |
| `src/deepflow_analyst/agent/pipeline.py` | 4 个 SQL 角色（generate / review / execute / interpret）· Z 采样投票 · X RAG 注入 |
| `src/deepflow_analyst/retrieval.py` | X · BM25 few-shot bank + `get_default_bank()` 缓存单例 |
| `src/deepflow_analyst/fewshot/examples.jsonl` | 23 条 example，打进 wheel（禁止和 golden 重叠） |
| `src/deepflow_analyst/evaluation.py` | Golden-dataset Execution Accuracy scorer + CLI (`deepflow-eval`) |
| `src/deepflow_analyst/main.py` | FastAPI `/health` + `/api/query`（多轮协议） |
| `src/deepflow_analyst/llm_client.py` | OpenRouter 薄封装（温度固化、模型路由预留） |
| `tests/golden/golden_dataset.jsonl` | 20 条 ground-truth NL→SQL 用例 |
| `.github/workflows/ci.yml` | backend + docker + evaluation 三 job |

---

## 当前基线

| 指标 | 值 | 备注 |
|------|-----|-----|
| Accuracy (local baseline N=1) | 12/20 = **60%** | deepseek-v3.2 · temp=0 · Z=off · RAG=off |
| Accuracy (local RAG N=1) | 14/20 = **70%** | X · 单独开 RAG |
| Accuracy (local RAG + Z N=3) | 14/20 = **70%** | 默认生产配置；Hard 2/5 = 40% |
| Accuracy (CI N=3, RAG=on) | 65-70%（预期） | 阈值 0.65 = 70% - 5pp provider buffer |
| Easy | 6/6 = 100% | |
| Medium | 6/9 = 67% | m04/m05 失败是 ORDER BY tiebreaker 与 golden 不一致（语义正确但字段选错） |
| Hard | 2/5 = 40% | 仍挂：h01（per-country DISTINCT ON）· h02（self-join 字符串拼接）· h05（per-genre DISTINCT ON）|
| `EVAL_THRESHOLD` | 0.65 | X 抬 ceiling 后阈值从 0.60 抬到 0.65 |

---

## Roadmap（按优先级）

- [x] W1 skeleton（Docker + FastAPI + React + PG + Chinook）
- [x] W6 E2E pipeline（单 LLM 版）
- [x] W10 evaluation gate（golden dataset + CI + 阈值）
- [x] prompt 工程（tie-break + 列精确性 → 45%→60%）
- [x] 4-role 架构（+ SQL Reviewer）
- [x] W8 HITL（LangGraph StateGraph + intent 分类 + 写拦截 + interrupt-resume 澄清）
- [x] Z · stability sampling（Writer N-sample × Reviewer × 结果集多数投票 · CI 阈值抬到 0.60）
- [x] X · few-shot RAG（BM25 over CJK 字符 unigram+bigram · 23 条独立 example bank · 注入 Writer system prompt · 60%→70%·Hard 20%→40%）
- [ ] W11 LLMOps（Langfuse tracing + ModelRouter）
- [ ] W12 Kubernetes 部署（Helm + HPA + NetworkPolicy）
- [ ] W14 路演 + 商业化文档

---

## 设计非目标（不要主动提/加）

- **CrewAI 框架依赖**——pattern 已经用手写 4-role 实现了（`graph.py` docstring 里写了怎么 1 行换成 Crew，给学员参考用）
- **多租户 / 认证系统**——这是单用户教学 demo
- **DB 写操作支持**——架构意图就是 read-only；write intent 被 intent classifier 短路拒绝
- **更复杂的 AutoML 类 Agent**——这是 Text-to-SQL 助手，不是通用数据科学平台

---

## 与用户协作的约定

1. **评估驱动**——每个改动都必须带一个可量化的 accuracy/latency/cost 指标，不用"感觉"代替数字
2. **不打断节奏**——用户说"按你建议"时继续推进，不要反复 ping-pong 确认
3. **敏感操作要确认**——commit / push / 改 secret / 动其他项目 / 删东西 前要先告知
4. **Secret 永不入 prompt / 文件 / 历史**——即使是 `.env.example` 也只放占位符
5. **优先基于已有技术栈**——引入新依赖（特别是 AI 框架）前要 justify 用数据，不是"这个框架听着不错"
