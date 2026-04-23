import {
  Alert,
  Box,
  Button,
  Container,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { getHealth, postQuery } from "./api";

export default function App() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState<string>("checking...");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then((h) => setHealth(`backend ${h.status} · db ${h.db}`))
      .catch((e) => setHealth(`unreachable (${String(e)})`));
  }, []);

  const handleSubmit = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await postQuery(question);
      setAnswer(resp.answer);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Container maxWidth="md" sx={{ py: 6 }}>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h4" fontWeight={700}>
            DeepFlow Analyst
          </Typography>
          <Typography variant="body2" color="text.secondary">
            企业数据分析智能体 · W1 骨架（Agent 流水线在 W6 接入）
          </Typography>
          <Typography variant="caption" color="text.secondary">
            status: {health}
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
            />
            <Box>
              <Button
                variant="contained"
                onClick={handleSubmit}
                disabled={loading || !question.trim()}
              >
                {loading ? "thinking..." : "提交"}
              </Button>
            </Box>
          </Stack>
        </Paper>

        {error && <Alert severity="error">{error}</Alert>}

        {answer && (
          <Paper variant="outlined" sx={{ p: 3, bgcolor: "grey.50" }}>
            <Typography variant="caption" color="text.secondary">
              后端响应
            </Typography>
            <Typography sx={{ mt: 1, whiteSpace: "pre-wrap" }}>{answer}</Typography>
          </Paper>
        )}
      </Stack>
    </Container>
  );
}
