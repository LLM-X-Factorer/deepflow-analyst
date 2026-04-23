export interface QueryResponse {
  answer: string;
  status: string;
}

export async function postQuery(question: string): Promise<QueryResponse> {
  const resp = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
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
