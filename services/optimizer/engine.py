from __future__ import annotations

def recommendations(applications: list[dict], period_days: int) -> list[dict]:
    results=[]; scale=30/max(period_days,1)
    for app in applications:
        name=app["application"]; spend=app["spend"]; requests=app["requests"] or 1
        if app["retry_rate"]>=.05:
            savings=app["retry_spend"]*.70*scale
            results.append(item("RETRY WASTE",f"Reduce retries in {name}",f"Retries represent {app['retry_rate']*100:.1f}% of requests and consumed ${app['retry_spend']:.2f} in the selected period.",savings,"HIGH" if app["retry_rate"]>.12 else "MEDIUM","LOW",name,app["model"],"Inspect retry policy, provider errors, and idempotency; cap automatic retries."))
        if app["failure_rate"]>=.02:
            savings=app["failed_spend"]*.60*scale
            results.append(item("FAILED REQUEST COST",f"Reduce failed generation cost in {name}",f"{app['failure_rate']*100:.1f}% of requests failed after consuming ${app['failed_spend']:.2f}.",savings,"HIGH","MEDIUM",name,app["model"],"Validate requests before inference and investigate the dominant error cluster."))
        if app["cache_rate"]<.10 and app["input_tokens"]>100_000:
            eligible=app["input_spend"]*.12*scale
            results.append(item("CACHE OPPORTUNITIES",f"Evaluate caching for {name}",f"Observed cache-hit rate is {app['cache_rate']*100:.1f}% across {app['input_tokens']:,.0f} input tokens. Eligibility is not known without content.",eligible,"MEDIUM","LOW",name,app["model"],"Measure stable-prefix reuse and run a privacy-safe cache pilot."))
        if app["context_utilization"]>.55 or app["input_output_ratio"]>12:
            savings=app["input_spend"]*.25*scale
            results.append(item("CONTEXT REDUCTION",f"Review context size for {name}",f"Average context utilization is {app['context_utilization']*100:.1f}% and input/output ratio is {app['input_output_ratio']:.1f}x.",savings,"MEDIUM","MEDIUM",name,app["model"],"Profile retrieved context, cap document count, and measure output impact before rollout."))
        if "premium" in app["model"].lower() and requests>=20:
            savings=spend*.45*scale
            results.append(item("MODEL ROUTING",f"Test economical routing for {name}",f"The premium model accounts for ${spend:.2f} across {requests:,} requests. Savings assume 45% lower price at identical observed volume; quality is not assumed equivalent.",savings,"MEDIUM","MEDIUM",name,app["model"],"Shadow-test a lower-cost model on low-complexity requests with user-supplied evaluations."))
    return sorted([x for x in results if x["estimated_monthly_savings"]>.001],key=lambda x:x["estimated_monthly_savings"],reverse=True)

def item(category,title,evidence,savings,confidence,risk,application,model,action):
    return {"category":category,"title":title,"reason":"A deterministic telemetry threshold was exceeded.","evidence":evidence,"estimated_monthly_savings":round(savings,2),"confidence":confidence,"risk":risk,"implementation_complexity":"LOW" if category in ("CACHE OPPORTUNITIES","RETRY WASTE") else "MEDIUM","affected_application":application,"affected_model":model,"recommended_action":action,"labels":{"evidence":"OBSERVED","savings":"ESTIMATED"}}
