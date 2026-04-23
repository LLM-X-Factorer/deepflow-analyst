# DeepFlow Analyst

> **企业数据分析智能体** — LLM+X 第二期（DeepFlow）结业项目参考实现
>
> 用自然语言提问，多 Agent 协作生成 SQL、在沙箱中执行、产出带图表的分析报告。
> 面向非技术的业务分析师 / 产品经理 / 运营 / 市场。

🚦 当前版本：`v0.2 · W6 E2E + W10 评估门禁` — 单 LLM 调用把"自然语言问题 → SQL → 执行 → 解读"打通，CI 里跑 Execution Accuracy 门禁。CrewAI / LangGraph / HITL / RAG / LLMOps 等在后续周次逐步替换升级。

---

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | FastAPI · Uvicorn · SQLAlchemy · Pydantic v2 |
| 前端 | React · Vite · MUI · TypeScript |
| 数据 | PostgreSQL 16 · Chinook 数据集 |
| LLM 网关 | OpenRouter（统一调 Claude / GPT / 开源模型） |
| 包管理 | `uv`（Python 3.11）· `pnpm`（Node） |
| 容器 | Docker · Docker Compose |
| CI | GitHub Actions |

后续周次增量引入：Milvus（W4）· CrewAI（W6）· MCP/E2B（W7）· LangGraph（W8-9）· DeepEval（W10）· Langfuse（W11）· Kubernetes（W12-13）。

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
- 后端：http://localhost:8090  （`/health` · `/docs`）
- 前端：http://localhost:5173  （W3 起可用）
- Postgres：`localhost:55433` · user/pass/db 均为 `deepflow`

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
├── src/deepflow_analyst/   # Python 包（src 布局）
│   ├── main.py             # FastAPI app
│   ├── settings.py         # pydantic-settings 配置
│   ├── llm_client.py       # OpenRouter 客户端
│   ├── db.py               # SQLAlchemy engine
│   ├── evaluation.py       # 评估主逻辑 + CLI（`deepflow-eval`）
│   └── agent/              # 查询流水线
│       └── pipeline.py     # generate_sql → validate → execute → interpret
├── tests/
│   ├── test_*.py           # 33 项单元测试 + mock LLM 集成
│   └── golden/             # 评估用黄金数据集（JSONL）
├── web/                    # React + Vite + MUI 前端
├── data/seed/              # Chinook SQL（git 忽略，脚本拉取）
├── scripts/                # 运维脚本
├── .github/workflows/      # CI
├── Dockerfile              # 多阶段构建
├── docker-compose.yml      # app + postgres
└── pyproject.toml          # uv / ruff / mypy / pytest 配置
```

---

## 评估门禁（Evaluation Gate）

CI 里第三个 job `evaluation` 会在 `pull_request` / `push to main` 时运行：

1. 起一个 PostgreSQL 16 service，灌入 Chinook
2. 跑 `uv run deepflow-eval`——对每条 golden case：生成 SQL → 执行 → 与 ground truth SQL 的执行结果做集合等价比较
3. 计算 **Execution Accuracy**；低于 `EVAL_THRESHOLD`（默认 0.50）则 fail
4. 上传 `evaluation_report.md` 为 artifact，并写入 PR 的 Step Summary

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

`tests/golden/golden_dataset.jsonl` 当前有 7 条（3 easy / 3 medium / 1 hard）。W10 教学环节学员要扩到 50+ 条——这也是 fork 成自己简历项目时最直观的 customization 点。格式说明见 `tests/golden/README.md`。

---

## 14 周 → 项目演进路线

| 周 | 本仓库新增 |
|----|----------|
| W1 | ✅ 项目骨架 · Docker · FastAPI · Postgres · Chinook |
| W2 | 产品画布 · PRD 文档 |
| W3 | ✅ 前端 React+MUI · 全栈打通（跨 W6 一起先拉通） |
| W4 | Schema RAG（Milvus · 向量化 DDL/业务语义 · 替换硬编码 schema） |
| W5 | 混合检索 · 查询重写 · Cross-Encoder 重排 |
| W6 | ✅ 首个端到端 Demo（单 LLM 简版）· CrewAI 四 Agent 版在教学周替换 |
| W7 | MCP · E2B 沙箱 · 外部 API |
| W8 | LangGraph 主流程 · Postgres Checkpointer |
| W9 | HITL（写操作拦截 · 意图澄清 · 敏感表审核） |
| W10 | ✅ 黄金数据集（7 条种子）· Execution Accuracy · CI 评估门禁；DeepEval 高级指标（Faithfulness / Relevancy）在 W11 教学周补充 |
| W11 | Langfuse · ModelRouter · 语义缓存 · FinOps |
| W12 | Kubernetes · Helm · HPA |
| W13 | 蓝绿部署 · 评估阈值门禁 |
| W14 | 商业化 · 定价 · GTM · 路演 |

---

## 如何把它改造成你自己的简历项目

本仓库是**教学参考实现**——骨架不动、换数据就是一个新行业的 AI 产品：

1. 替换 `data/seed/` 下的业务数据（金融 / 医疗 / 电商 / 游戏 / 法律 …）
2. 替换 `src/deepflow_analyst/rag/schema_docs.md`（W4 会创建）里的字段语义
3. 替换 `tests/golden/golden_dataset.jsonl`（W10 会创建）里的典型查询
4. 调整 HITL 规则里的"敏感表白名单"

技术骨架（CrewAI 协作 · LangGraph 编排 · E2B 沙箱 · DeepEval 评估 · Langfuse 观测 · K8s 部署 · 评估门禁 CI/CD）完全复用。

---

## License

MIT © 2026 LLM+X Course
