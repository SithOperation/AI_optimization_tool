# TokenScope

**Free, open-source, local-first AI usage intelligence.** TokenScope monitors token usage, estimates spend, and provides a foundation for explainable forecasting and optimization. It requires no commercial AI account, cloud service, API key, or external telemetry.

Milestones 1 through 7 provide a local analytics platform with ingestion, analytics, forecasts, optimization, scenarios, adapters, optional secret-safe provider configuration, audit logs, retention, exports, authentication, rate limiting, and CI.

## Quick start

Windows:

```powershell
.\scripts\dev.ps1
```

Linux/macOS:

```sh
./scripts/dev.sh
```

Open <http://127.0.0.1:3000> and select **Explore Demo Data**.

## Docker

```sh
docker compose up --build
```

Services bind to localhost by default. FastAPI documentation is at <http://127.0.0.1:8000/docs>.

## Manual start

```sh
python -m pip install -r apps/api/requirements.txt
python -m uvicorn tokenscope_api.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
npm install
npm run dev -- --host 127.0.0.1 --port 3000
```

## Submit telemetry

```sh
curl -X POST http://127.0.0.1:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{"application":"SOC Copilot","provider":"ollama","model":"llama-3.1-8b","input_tokens":1200,"output_tokens":180,"latency_ms":540}'
```

Refresh the dashboard to see the event in the server-side aggregates. Batch ingestion accepts up to 1,000 events at `/api/v1/events/batch`.

## Usage, costs, imports, and pricing

The Usage and Costs pages group telemetry by provider, model, department, team, application, workload, day, or hour. Date and organizational filters persist locally between pages.

The Import Data page previews CSV or JSON, automatically recognizes common field aliases, and reports rejected rows before committing anything. Pricing includes a versioned bundled registry and local overrides; overrides affect future events so historical estimates remain reproducible.

## Privacy and architecture

TokenScope does not phone home. The Milestone 1 schema has no prompt or response fields, and identity mode defaults to anonymous. The stack is a responsive web console, FastAPI/Pydantic, SQLAlchemy, indexed SQLite, deterministic pricing, seeded demo telemetry, and aggregation endpoints that keep raw events out of the browser.

See [architecture](docs/architecture.md), [telemetry](docs/telemetry.md), and [privacy](docs/privacy.md).

Forecast methodology and safety limits are documented in [forecasting](docs/forecasting.md).

See also [anomalies](docs/anomalies.md), [optimization](docs/optimization.md), and [budgets](docs/budgets.md).

Scenario assumptions and formulas are documented in [Scenario Lab](docs/scenario-lab.md).

Local adapters and instrumentation examples are documented in [integrations](docs/integrations.md).

Deployment hardening is documented in [security](docs/security.md).

## Roadmap

1. Optional commercial-provider integrations and enterprise hardening

Apache-2.0 licensed. Contributions are welcome.
