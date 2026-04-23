export type QueryStatus =
  | "ok"
  | "error"
  | "awaiting_clarification"
  | "write_rejected";

export interface QueryResponse {
  status: QueryStatus;
  thread_id: string;
  answer: string;
  sql?: string | null;
  columns?: string[] | null;
  rows?: unknown[][] | null;
  row_count?: number | null;
  clarification_question?: string | null;
  error?: string | null;
}

export interface QueryRequest {
  question?: string;
  thread_id?: string;
  resume_input?: string;
}

export async function postQuery(req: QueryRequest): Promise<QueryResponse> {
  const resp = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function getHealth(): Promise<Record<string, string>> {
  const resp = await fetch("/health");
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}
