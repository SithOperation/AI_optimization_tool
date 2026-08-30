# Live operations and reports

`GET /api/v1/live/stream` provides local Server-Sent Events every two seconds. Each event contains the last minute's request count, token count, estimated hourly cost, active applications, and errors. `GET /api/v1/live/snapshot` provides the same data once.

The executive report combines observed usage, estimated spend and savings, current budgets, anomalies, leading applications/models, and the most recent persisted forecast. Every category retains an OBSERVED, ESTIMATED, or FORECASTED label. JSON and CSV formats are available.

## AI Efficiency

The 0–100 score is a documented weighted sum:

- cost efficiency: 20%
- cache efficiency: 15%
- retry efficiency: 20%
- failure efficiency: 20%
- context efficiency: 15%
- reliability: 10%

Each normalized component and weight is returned by the API. The score measures operational efficiency—not output quality, business value, or user outcomes.
