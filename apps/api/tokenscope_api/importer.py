import csv
import io
import json

from pydantic import ValidationError

from .schemas import EventCreate, ImportRequest

ALIASES = {"prompt_tokens":"input_tokens","completion_tokens":"output_tokens","total_cost":"estimated_total_cost","app":"application","model_name":"model","vendor":"provider","time":"timestamp"}
FIELDS = set(EventCreate.model_fields)

def parse_import(payload: ImportRequest):
    if payload.format == "csv":
        rows = list(csv.DictReader(io.StringIO(payload.content.lstrip("\ufeff"))))
    else:
        decoded = json.loads(payload.content)
        rows = decoded if isinstance(decoded, list) else decoded.get("events", [])
    if len(rows) > 10_000: raise ValueError("Imports are limited to 10,000 rows")
    mapping = {key: payload.mapping.get(key, ALIASES.get(key, key if key in FIELDS else "")) for key in (rows[0].keys() if rows else [])}
    accepted, rejected = [], []
    integer_fields={"input_tokens","output_tokens","cached_input_tokens","reasoning_tokens","total_tokens","retry_count","status_code","context_window"}
    float_fields={"latency_ms","time_to_first_token_ms","tokens_per_second","estimated_input_cost","estimated_output_cost","estimated_total_cost","context_utilization"}
    boolean_fields={"success","cache_hit"}
    for index,row in enumerate(rows, start=2 if payload.format=="csv" else 1):
        try:
            transformed={}
            for source,value in row.items():
                target=mapping.get(source)
                if not target or value in (None,""): continue
                if target in integer_fields: value=int(value)
                elif target in float_fields: value=float(value)
                elif target in boolean_fields: value=str(value).lower() in ("true","1","yes")
                transformed[target]=value
            accepted.append(EventCreate.model_validate(transformed))
        except (ValidationError,ValueError,TypeError) as error:
            rejected.append({"row":index,"reason":str(error).splitlines()[0]})
    return mapping, accepted, rejected
