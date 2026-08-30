#!/usr/bin/env sh
curl -fsS -X POST http://127.0.0.1:8000/api/v1/events \
  -H 'Content-Type: application/json' \
  -d '{"application":"Local Assistant","provider":"ollama","model":"llama-3.1-8b","input_tokens":1200,"output_tokens":180,"latency_ms":540}'
