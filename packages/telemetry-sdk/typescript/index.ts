export type TokenScopeEvent = {
  application: string; provider: string; model: string;
  input_tokens?: number; output_tokens?: number; latency_ms?: number;
  department?: string; team?: string; workload?: string; success?: boolean;
};

export async function recordEvent(event: TokenScopeEvent, baseUrl = "http://127.0.0.1:8000") {
  const response = await fetch(`${baseUrl}/api/v1/events`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(event),
  });
  if (!response.ok) throw new Error(`TokenScope rejected event: ${response.status}`);
  return response.json();
}
