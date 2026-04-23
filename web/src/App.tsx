import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { getHealth, postQuery, type QueryResponse } from "./api";

const SAMPLE_QUESTIONS = [
  "销售额最高的 5 个国家分别是哪些？",
  "曲目最多的 10 位艺人",
  "销量是多少？", // intentionally ambiguous — demos the clarify flow
  "删除所有测试账户", // demos the write-intent rejection
];

export default function App() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState("checking...");
  const [clarifyAnswer, setClarifyAnswer] = useState("");

  useEffect(() => {
    getHealth()
      .then((h) => setHealth(`backend ${h.status} · db ${h.db} · env ${h.env}`))
      .catch((e) => setHealth(`unreachable (${String(e)})`));
  }, []);

  const submitNew = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setResult(null);
    setClarifyAnswer("");
    try {
      const resp = await postQuery({ question });
      setResult(resp);
    } catch (e) {
      setResult({
        status: "error",
        thread_id: "",
        answer: "网络或后端错误",
        error: String(e),
      });
    } finally {
      setLoading(false);
    }
  };

  const submitClarification = async () => {
    if (!result || result.status !== "awaiting_clarification") return;
    if (!clarifyAnswer.trim()) return;
    setLoading(true);
    try {
      const resp = await postQuery({
        thread_id: result.thread_id,
        resume_input: clarifyAnswer,
      });
      setResult(resp);
      setClarifyAnswer("");
    } catch (e) {
      setResult({
        status: "error",
        thread_id: result.thread_id,
        answer: "resume 失败",
        error: String(e),
      });
    } finally {
      setLoading(false);
    }
  };

  const awaiting = result?.status === "awaiting_clarification";
  const rejected = result?.status === "write_rejected";
  const ok = result?.status === "ok";
  const errored = result?.status === "error";

  return (
    <Container maxWidth="lg" sx={{ py: 5 }}>
      <Stack spacing={3}>
        <Box>
          <Stack direction="row" alignItems="baseline" spacing={1.5}>
            <Typography variant="h4" fontWeight={700}>
              DeepFlow Analyst
            </Typography>
            <Chip label="W8 HITL" size="small" color="primary" variant="outlined" />
          </Stack>
          <Typography variant="body2" color="text.secondary">
            LangGraph 多 Agent · 写操作自动拦截 · 意图歧义时反问澄清
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {health}
          </Typography>
        </Box>

        <Paper variant="outlined" sx={{ p: 3 }}>
          <Stack spacing={2}>
            <TextField
              label="用自然语言提问"
              placeholder="例：上季度销量 Top 10 的曲目有哪些？"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              multiline
              minRows={2}
              fullWidth
              disabled={awaiting || loading}
            />
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {SAMPLE_QUESTIONS.map((s) => (
                <Chip
                  key={s}
                  label={s}
                  size="small"
                  onClick={() => {
                    setQuestion(s);
                    setResult(null);
                  }}
                  sx={{ cursor: "pointer" }}
                  disabled={awaiting || loading}
                />
              ))}
            </Stack>
            <Box>
              <Button
                variant="contained"
                onClick={submitNew}
                disabled={loading || !question.trim() || awaiting}
              >
                {loading && !awaiting ? "thinking..." : "提交"}
              </Button>
            </Box>
          </Stack>
        </Paper>

        {awaiting && (
          <Paper variant="outlined" sx={{ p: 3, bgcolor: "warning.50", borderColor: "warning.main" }}>
            <Stack spacing={2}>
              <Box>
                <Typography variant="overline" color="warning.main">
                  需要你澄清一下
                </Typography>
                <Typography sx={{ mt: 0.5 }}>{result?.clarification_question}</Typography>
              </Box>
              <TextField
                label="你的回答"
                value={clarifyAnswer}
                onChange={(e) => setClarifyAnswer(e.target.value)}
                fullWidth
                size="small"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && clarifyAnswer.trim()) {
                    e.preventDefault();
                    submitClarification();
                  }
                }}
              />
              <Box>
                <Button
                  variant="contained"
                  color="warning"
                  onClick={submitClarification}
                  disabled={loading || !clarifyAnswer.trim()}
                >
                  {loading ? "resuming..." : "回答并继续"}
                </Button>
              </Box>
            </Stack>
          </Paper>
        )}

        {rejected && (
          <Alert severity="error" variant="outlined">
            <Typography variant="body2" fontWeight={600}>
              {result?.answer}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              thread_id: {result?.thread_id}
            </Typography>
          </Alert>
        )}

        {errored && (
          <Alert severity="error">
            <Typography variant="body2" fontWeight={600}>
              {result?.answer}
            </Typography>
            {result?.error && (
              <Typography variant="caption" sx={{ fontFamily: "monospace" }}>
                {result.error}
              </Typography>
            )}
          </Alert>
        )}

        {ok && (
          <Stack spacing={2}>
            <Paper variant="outlined" sx={{ p: 3 }}>
              <Typography variant="overline" color="text.secondary">
                解读
              </Typography>
              <Typography sx={{ mt: 0.5, whiteSpace: "pre-wrap" }}>{result?.answer}</Typography>
            </Paper>

            {result?.sql && (
              <Paper variant="outlined" sx={{ p: 2, bgcolor: "grey.900", color: "grey.100" }}>
                <Typography variant="overline" sx={{ color: "grey.400" }}>
                  generated SQL
                </Typography>
                <Box
                  component="pre"
                  sx={{
                    m: 0,
                    mt: 0.5,
                    fontFamily: "monospace",
                    fontSize: 13,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {result.sql}
                </Box>
              </Paper>
            )}

            {result?.columns && result?.rows && (
              <Paper variant="outlined">
                <Box sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: "divider" }}>
                  <Typography variant="overline" color="text.secondary">
                    结果 · {result.row_count ?? result.rows.length} 行
                  </Typography>
                </Box>
                <TableContainer sx={{ maxHeight: 400 }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        {result.columns.map((col) => (
                          <TableCell key={col} sx={{ fontWeight: 600 }}>
                            {col}
                          </TableCell>
                        ))}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {result.rows.slice(0, 100).map((row, i) => (
                        <TableRow key={i}>
                          {row.map((cell, j) => (
                            <TableCell key={j}>{String(cell ?? "")}</TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            )}
          </Stack>
        )}
      </Stack>
    </Container>
  );
}
