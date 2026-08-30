from datetime import datetime, timezone

def attrs(items):
    result={}
    for item in items or []:
        value=item.get("value",{}); result[item.get("key")]=next(iter(value.values()),None)
    return result

def normalize_otlp(payload: dict) -> tuple[list[dict],list[dict]]:
    events=[];errors=[]
    for resource in payload.get("resourceSpans",[]):
        resource_attrs=attrs(resource.get("resource",{}).get("attributes",[]))
        for scope in resource.get("scopeSpans",[]):
            for span in scope.get("spans",[]):
                try:
                    a={**resource_attrs,**attrs(span.get("attributes",[]))}; model=a.get("gen_ai.response.model") or a.get("gen_ai.request.model") or a.get("llm.model_name")
                    if not model: continue
                    start=int(span.get("startTimeUnixNano",0));end=int(span.get("endTimeUnixNano",start))
                    inp=int(a.get("gen_ai.usage.input_tokens") or a.get("llm.usage.prompt_tokens") or 0);out=int(a.get("gen_ai.usage.output_tokens") or a.get("llm.usage.completion_tokens") or 0)
                    events.append({"event_id":span.get("spanId"),"timestamp":datetime.fromtimestamp(start/1e9,tz=timezone.utc) if start else datetime.now(timezone.utc),"organization":a.get("service.namespace","default"),"department":a.get("tokenscope.department"),"team":a.get("tokenscope.team"),"application":a.get("service.name","OpenTelemetry application"),"workload":a.get("gen_ai.operation.name"),"provider":a.get("gen_ai.provider.name") or a.get("gen_ai.system") or "unknown","model":model,"request_id":a.get("gen_ai.request.id"),"input_tokens":inp,"output_tokens":out,"cached_input_tokens":int(a.get("gen_ai.usage.cache_read.input_tokens") or 0),"reasoning_tokens":int(a.get("gen_ai.usage.reasoning_tokens") or 0),"total_tokens":inp+out,"latency_ms":max(0,(end-start)/1e6),"success":span.get("status",{}).get("code") not in ("STATUS_CODE_ERROR",2),"error_type":span.get("status",{}).get("message"),"source":"opentelemetry","request_tags":{"otel.trace_id":span.get("traceId","")}})
                except (TypeError,ValueError) as error: errors.append({"span_id":span.get("spanId"),"reason":str(error)})
    return events,errors
