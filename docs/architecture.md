# Architecture

The browser requests aggregated results from a local FastAPI service. FastAPI validates vendor-neutral events with Pydantic, estimates costs from the local pricing registry, and persists them through SQLAlchemy to SQLite. The dashboard never downloads raw event history. ClickHouse remains an optional future scale-out backend.
