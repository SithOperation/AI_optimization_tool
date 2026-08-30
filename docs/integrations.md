# Integrations

TokenScope accepts OpenTelemetry GenAI OTLP/HTTP JSON at `POST /api/v1/otlp/v1/traces`. Existing instrumentation can keep its current spans; the adapter recognizes standard model, provider, input/output token, operation, duration, and error attributes.

LiteLLM success/failure callbacks can be forwarded to `POST /api/v1/integrations/litellm/events`. TokenScope extracts model, provider, tokens, cached tokens, cost, latency, team/application metadata, and errors. User identity remains excluded by default.

Ollama, vLLM, and generic OpenAI-compatible response envelopes can be posted to `/api/v1/integrations/compatible/events`. The connection wizard tests `/api/tags` for Ollama and `/v1/models` for compatible servers.

## Network safety

Milestone 6 endpoint connections are restricted to localhost and private-network addresses. URLs cannot contain embedded credentials. This reduces server-side request forgery risk and keeps local-first behavior explicit.

## SDK examples

Dependency-free Python and TypeScript helpers live in `packages/telemetry-sdk`. Curl and LiteLLM payload examples live in `examples`.

Commercial AI providers are optional, disabled, and not required for TokenScope.
