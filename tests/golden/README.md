# Golden Dataset — Execution Accuracy Benchmark

每一行一个用例（JSON Lines），结构：

| 字段 | 说明 |
|------|------|
| `id` | 短唯一 ID（`e01` / `m02` / `h01`） |
| `question` | 用户会问的自然语言问题 |
| `expected_sql` | 基准答案 SQL（由人工编写校对） |
| `difficulty` | `easy` / `medium` / `hard` |
| `tags` | 可选：标签分类，便于 W11 分组分析 |

## 评分方法：Execution Accuracy

1. 让 pipeline 根据 `question` 生成 SQL
2. 执行生成的 SQL 得到 rows_A
3. 执行 `expected_sql` 得到 rows_B
4. 判等规则：
   - 行数必须相等
   - 若 `expected_sql` 含 `ORDER BY` → 顺序敏感比较
   - 否则 → 行多集（multi-set）等价比较

## 如何扩充

直接 append 新行。保持 `id` 全局唯一。在 `scripts/evaluate.py` 本地跑一次确认新用例的 `expected_sql` 自己能跑通（别把 ground truth 写错）。

## 当前规模

本仓库作为教学参考实现，提供 **7 个种子用例**（3 easy / 3 medium / 1 hard）。课程 W10 的任务之一就是**扩充到 50+ 用例**——这是学员 fork 成自己简历项目时最容易体现"我理解评估驱动开发"的地方。
