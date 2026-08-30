def clamp(value): return round(max(0,min(100,value)),1)

WEIGHTS={"cost_efficiency":.20,"cache_efficiency":.15,"retry_efficiency":.20,"failure_efficiency":.20,"context_efficiency":.15,"reliability":.10}

def efficiency_score(*,requests,spend,cached_tokens,input_tokens,retries,failures,context_utilization):
    requests=max(requests,1);input_tokens=max(input_tokens,1)
    components={
        "cost_efficiency":clamp(100-(spend/requests)*500),
        "cache_efficiency":clamp((cached_tokens/input_tokens)/.25*100),
        "retry_efficiency":clamp(100-(retries/requests)*400),
        "failure_efficiency":clamp(100-(failures/requests)*500),
        "context_efficiency":clamp(100-max(0,context_utilization-.35)*120),
        "reliability":clamp((requests-failures)/requests*100),
    }
    score=round(sum(components[key]*weight for key,weight in WEIGHTS.items()),1)
    return {"score":score,"components":components,"weights":WEIGHTS,"formula":"Weighted sum of six normalized operational efficiency components","disclaimer":"This score measures operational efficiency, not business value or output quality."}
