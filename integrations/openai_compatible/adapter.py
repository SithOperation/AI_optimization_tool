from datetime import datetime, timezone

def normalize_response(wrapper) -> dict:
    payload=wrapper.payload;usage=payload.get("usage",{});details=usage.get("prompt_tokens_details") or {}
    inp=int(usage.get("prompt_tokens") or payload.get("prompt_eval_count") or 0);out=int(usage.get("completion_tokens") or payload.get("eval_count") or 0)
    duration=payload.get("total_duration",0);latency=duration/1_000_000 if duration else payload.get("latency_ms",0)
    return {"timestamp":datetime.now(timezone.utc),"application":wrapper.application,"department":wrapper.department,"team":wrapper.team,"workload":wrapper.workload,"provider":wrapper.provider or wrapper.source,"model":payload.get("model","unknown"),"input_tokens":inp,"output_tokens":out,"cached_input_tokens":int(details.get("cached_tokens",0)),"total_tokens":int(usage.get("total_tokens") or inp+out),"latency_ms":max(0,float(latency or 0)),"success":not bool(payload.get("error")),"error_type":str(payload.get("error")) if payload.get("error") else None,"source":wrapper.source}
