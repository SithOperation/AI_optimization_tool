# Telemetry

Submit one event to `POST /api/v1/events` or up to 1,000 events to `/api/v1/events/batch`. Required fields are `application`, `provider`, and `model`. Token counts must be non-negative. Prompt text, response text, and user identity are intentionally absent from the default schema.

```json
{"application":"SOC Copilot","provider":"ollama","model":"llama-3.1-8b","input_tokens":1200,"output_tokens":180,"latency_ms":540}
```
