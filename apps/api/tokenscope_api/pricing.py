from dataclasses import asdict, dataclass
from datetime import date

@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cached: float
    provider: str = "Local / Demo"
    currency: str = "USD"
    effective_date: str = "2026-01-01"
    source: str = "TokenScope bundled registry"
    last_verified: str = "2026-08-30"

PRICES = {
    "llama-3.1-8b": Price(.10, .10, .03),
    "llama-3.1-70b": Price(.72, .72, .20),
    "qwen2.5-coder-32b": Price(.45, .65, .12),
    "mistral-small": Price(.20, .60, .05),
    "generic-economy": Price(.50, 1.50, .15, "Generic"),
    "generic-premium": Price(3.00, 12.00, .75, "Generic"),
}

def get_price(model: str, db=None) -> Price:
    if db is not None:
        from .models import PriceOverride
        custom = db.get(PriceOverride, model.lower()) or db.get(PriceOverride, model)
        if custom:
            return Price(custom.input_price_per_million, custom.output_price_per_million, custom.cached_input_price_per_million, custom.provider, custom.currency, custom.effective_date, custom.source, custom.last_verified)
    return PRICES.get(model.lower(), Price(.50, 1.50, .15, "Fallback", effective_date=str(date.today()), source="TokenScope fallback estimate", last_verified=str(date.today())))

def calculate(model: str, input_tokens: int, output_tokens: int, cached_tokens: int, db=None) -> tuple[float, float, float]:
    price = get_price(model, db)
    uncached = max(0, input_tokens - cached_tokens)
    input_cost = (uncached * price.input + cached_tokens * price.cached) / 1_000_000
    output_cost = output_tokens * price.output / 1_000_000
    return input_cost, output_cost, input_cost + output_cost

def registry(db=None) -> list[dict]:
    rows = [{"model_id": model, **{ "input_price_per_million": p.input, "output_price_per_million": p.output, "cached_input_price_per_million": p.cached, "provider": p.provider, "currency": p.currency, "effective_date": p.effective_date, "source": p.source, "last_verified": p.last_verified}, "custom": False} for model,p in PRICES.items()]
    if db is not None:
        from .models import PriceOverride
        for item in db.query(PriceOverride).all():
            row={column.name:getattr(item,column.name) for column in item.__table__.columns}; row["custom"]=True
            rows=[existing for existing in rows if existing["model_id"] != item.model_id]; rows.append(row)
    return sorted(rows, key=lambda x:(x["provider"],x["model_id"]))
