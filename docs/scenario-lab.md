# Scenario Lab

Scenario Lab contains three deterministic calculators. No LLM or external service is used.

## Organization capacity

Inputs include employees, active adoption, requests per user, input/output tokens, working days, growth, cache rate, retry rate, and a model-price mix. The model mix must total 100%. Outputs include monthly requests and attempts, tokens, spend, annual run rate, next-month spend, cache savings, retry overhead, and model distribution.

## Model migration

TokenScope reads an application's observed token volume and compares it with an alternative model price. The comparison is cost-only. Output quality is not assumed equivalent and must be validated with user-provided evaluations.

## Local versus cloud

Cloud cost uses input/output prices. Local cost includes hardware amortization, utilization-adjusted electricity, hosting, and maintenance. Throughput estimates capacity, cost per million tokens, required utilization, and the approximate break-even token volume.

All outputs are estimates based on user-supplied assumptions. Reliability, staffing, networking, redundancy, and model quality may require additional adjustment.
