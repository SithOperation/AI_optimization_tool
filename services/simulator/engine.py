from __future__ import annotations

HOURS_MONTH=730

def organization_scenario(data):
    share=sum(item.share_percent for item in data.model_mix)
    if abs(share-100)>0.01: raise ValueError(f"Model mix must total 100%; received {share:.2f}%")
    active=data.active_ai_users if data.active_ai_users is not None else round(data.employees*data.adoption_percent/100)
    active=min(active,data.employees)
    base_requests=active*data.requests_per_user_day*data.working_days_month
    monthly_requests=base_requests*(1+data.application_growth_percent/100)
    attempts=monthly_requests*(1+data.retry_percent/100)
    input_tokens=attempts*data.average_input_tokens; output_tokens=attempts*data.average_output_tokens
    cache_rate=data.cache_hit_percent/100; uncached_input=input_tokens*(1-cache_rate)
    distributions=[];spend=0
    for item in data.model_mix:
        fraction=item.share_percent/100
        model_cost=(uncached_input*fraction*item.input_price_per_million+output_tokens*fraction*item.output_price_per_million)/1_000_000
        spend+=model_cost;distributions.append({"model":item.model,"share_percent":item.share_percent,"requests":monthly_requests*fraction,"tokens":(input_tokens+output_tokens)*fraction,"spend":model_cost})
    no_cache_spend=sum((input_tokens*(x.share_percent/100)*x.input_price_per_million+output_tokens*(x.share_percent/100)*x.output_price_per_million)/1_000_000 for x in data.model_mix)
    next_month=spend*(1+data.monthly_growth_percent/100)
    return {"scenario":data.name,"active_ai_users":active,"monthly_requests":monthly_requests,"monthly_attempts":attempts,"monthly_input_tokens":input_tokens,"monthly_output_tokens":output_tokens,"monthly_total_tokens":input_tokens+output_tokens,"monthly_spend":spend,"annual_spend":spend*12,"next_month_spend":next_month,"cache_savings":max(0,no_cache_spend-spend),"retry_overhead_requests":attempts-monthly_requests,"distribution":distributions,"assumptions":{"working_days_month":data.working_days_month,"growth_percent":data.monthly_growth_percent,"quality_equivalence_assumed":False}}

def local_vs_cloud(data):
    total_tokens=data.monthly_input_tokens+data.monthly_output_tokens
    cloud=(data.monthly_input_tokens*data.cloud_input_price_per_million+data.monthly_output_tokens*data.cloud_output_price_per_million)/1_000_000
    amortization=data.gpu_quantity*data.gpu_purchase_price/data.hardware_life_months
    electricity=data.gpu_quantity*data.power_draw_watts/1000*HOURS_MONTH*(data.utilization_percent/100)*data.electricity_rate_kwh
    local_monthly=amortization+electricity+data.monthly_maintenance_cost+data.monthly_hosting_cost
    capacity=data.estimated_tokens_second*3600*HOURS_MONTH*(data.utilization_percent/100)*data.gpu_quantity
    local_per_million=local_monthly/(capacity/1_000_000) if capacity else None
    cloud_per_million=cloud/(total_tokens/1_000_000) if total_tokens else 0
    variable_cloud_per_token=cloud/total_tokens if total_tokens else 0
    break_even_tokens=local_monthly/variable_cloud_per_token if variable_cloud_per_token else None
    return {"cloud_monthly_cost":cloud,"local_monthly_cost":local_monthly,"monthly_difference":cloud-local_monthly,"local_cost_per_million_at_capacity":local_per_million,"cloud_cost_per_million_at_workload":cloud_per_million,"estimated_monthly_capacity_tokens":capacity,"capacity_utilization_required_percent":total_tokens/capacity*100 if capacity else None,"break_even_monthly_tokens":break_even_tokens,"components":{"hardware_amortization":amortization,"electricity":electricity,"maintenance":data.monthly_maintenance_cost,"hosting":data.monthly_hosting_cost},"assumptions":{"hours_per_month":HOURS_MONTH,"quality_equivalence_assumed":False,"capacity_is_throughput_estimate":True}}
