from datetime import datetime, timezone

def normalize_litellm(payload: dict, collect_identity: bool=False) -> dict:
    info=payload.get("litellm_params",{});usage=payload.get("usage") or payload.get("response_cost",{}).get("usage",{}) or {};metadata=info.get("metadata") or payload.get("metadata") or {}
    model=payload.get("model") or info.get("model") or "unknown";provider=payload.get("custom_llm_provider") or info.get("custom_llm_provider") or (model.split("/",1)[0] if "/" in model else "litellm")
    inp=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0);out=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    start=payload.get("start_time");end=payload.get("end_time");latency=payload.get("latency_ms",0)
    if start and end:
        try: latency=(datetime.fromisoformat(str(end).replace("Z","+00:00"))-datetime.fromisoformat(str(start).replace("Z","+00:00"))).total_seconds()*1000
        except ValueError: pass
    tags={"litellm.api_key_alias":metadata.get("user_api_key_alias","")}
    if collect_identity and metadata.get("user_api_key_user_id"): tags["litellm.user_id"]=metadata["user_api_key_user_id"]
    cost=payload.get("response_cost"); cost=cost if isinstance(cost,(int,float)) else None
    return {"timestamp":datetime.now(timezone.utc),"application":metadata.get("application") or metadata.get("user_api_key_team_alias") or "LiteLLM application","department":metadata.get("department"),"team":metadata.get("user_api_key_team_alias"),"workload":metadata.get("workload"),"provider":provider,"model":model.split("/",1)[-1],"input_tokens":inp,"output_tokens":out,"cached_input_tokens":int((usage.get("prompt_tokens_details") or {}).get("cached_tokens",0)),"total_tokens":int(usage.get("total_tokens") or inp+out),"latency_ms":max(0,float(latency or 0)),"success":payload.get("exception") is None,"error_type":str(payload.get("exception")) if payload.get("exception") else None,"estimated_total_cost":cost,"source":"litellm","request_tags":tags,"identity_mode":"hashed" if collect_identity else "anonymous"}
