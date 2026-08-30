# Security and enterprise deployment

TokenScope binds its documented development workflow to localhost. Set `TOKENSCOPE_API_KEY` before network exposure; clients send it through `X-TokenScope-Key`. Production deployments should also use TLS, network allowlists, and a reverse proxy or future OIDC integration.

Ingestion uses a configurable per-client sliding-window rate limit and a 5 MB request limit. Responses include content-type, framing, referrer, permissions, and content-security headers. Structured logs record method, path, status, and duration without query strings, bodies, credentials, prompts, or responses.

Commercial provider configuration stores environment-variable names—not values. Configuration exports exclude secrets. CSV exports prefix spreadsheet-formula characters.

Retention never deletes automatically. Administrators configure a window and invoke a separate apply endpoint. Configuration changes appear in the local audit log.
