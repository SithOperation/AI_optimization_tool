# Forecasting

TokenScope forecasts requests, input tokens, output tokens, total tokens, and spend locally with StatsForecast. It does not send telemetry to an LLM.

## Selection

The engine compares Naive, Seasonal Naive, AutoETS, AutoARIMA, and Theta. MSTL is added when at least 56 daily observations are available. It holds out the most recent 7–14 observations, measures symmetric mean absolute percentage error (sMAPE), and selects the lowest-error successful candidate.

The selected model is retrained on the complete series. Results include expected values and a 95% prediction interval. Each run persists its training period, model, error, candidate results, forecast values, and deterministic driver explanations.

## Safety rules

- At least 21 daily observations are required.
- The requested horizon cannot exceed three times the available history.
- A 12-month forecast requires at least 120 observations.
- Failed candidate models remain visible in backtest evidence.
- Results are labeled forecasts and historical estimates, never guarantees.

The API returns HTTP 422 with actionable guidance when history is insufficient.
