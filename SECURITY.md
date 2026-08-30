# Security

TokenScope binds to localhost by default and collects metadata only. Do not expose the development server publicly. Report vulnerabilities privately to the project maintainers and do not include telemetry or credentials in reports.

Before non-local deployment, set `TOKENSCOPE_API_KEY`, use TLS, restrict network access, and configure retention. Provider credentials must use environment variables; values are never stored in configuration exports.
