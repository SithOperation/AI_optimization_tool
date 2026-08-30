import math
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import TelemetryEvent
from .pricing import calculate

APPS = [
    ("Code Assistant", "Engineering", "Developer Tools", "qwen2.5-coder-32b", 1.5),
    ("SOC Copilot", "Security", "Threat Analysis", "llama-3.1-70b", .7),
    ("Customer Support Agent", "Support", "Ticket Resolution", "llama-3.1-8b", 1.8),
    ("Document Analyzer", "Finance", "Document Extraction", "mistral-small", .8),
    ("Marketing Writer", "Marketing", "Content Generation", "generic-premium", .45),
    ("Internal Knowledge Search", "IT", "Knowledge Retrieval", "llama-3.1-8b", 1.0),
    ("Invoice Processor", "Operations", "Invoice Extraction", "mistral-small", .65),
]

def generate_demo(db: Session, days: int = 30, seed: int = 4217) -> int:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    rows = []
    for day in range(days, 0, -1):
        date = now - timedelta(days=day)
        weekday = .55 if date.weekday() >= 5 else 1.0
        growth = 1 + (days-day) * .006
        for app, dept, workload, model, weight in APPS:
            count = max(3, int(18 * weight * weekday * growth + rng.gauss(0, 2)))
            for n in range(count):
                spike = 2.5 if app == "Code Assistant" and day in (7, 8) else 1
                inp = max(100, int(rng.lognormvariate(7.7, .45) * spike))
                out = max(30, int(rng.lognormvariate(5.8, .38)))
                cached = int(inp * (.31 if app == "Customer Support Agent" and day < 12 else .08) * rng.random())
                retry = 1 if app == "SOC Copilot" and 12 <= day <= 15 and rng.random() < .3 else 0
                success = rng.random() > (.025 + retry*.1)
                ci, co, total = calculate(model, inp, out, cached)
                rows.append(TelemetryEvent(
                    timestamp=date.replace(hour=8+n%11, minute=rng.randrange(60), second=rng.randrange(60)),
                    organization="Example Manufacturing Corp", department=dept, team=dept,
                    application=app, workload=workload, provider="Local / Demo", model=model,
                    model_family=model.split('-')[0], deployment_type="local", input_tokens=inp,
                    output_tokens=out, cached_input_tokens=cached, total_tokens=inp+out,
                    latency_ms=max(80, rng.gauss(1200, 350)), success=success,
                    status_code=200 if success else 500, error_type=None if success else "generation_error",
                    retry_count=retry, cache_hit=cached > 0, estimated_input_cost=ci,
                    estimated_output_cost=co, estimated_total_cost=total, context_window=32768,
                    context_utilization=min(1, inp/32768), source="demo", request_tags={"demo":"true"}
                ))
    db.add_all(rows)
    db.commit()
    return len(rows)
