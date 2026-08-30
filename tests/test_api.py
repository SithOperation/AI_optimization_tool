from fastapi.testclient import TestClient

from apps.api.tokenscope_api.database import Base, engine
from apps.api.tokenscope_api.main import app
from apps.api.tokenscope_api.pricing import calculate
from services.anomaly.engine import detect

def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

def test_health_and_empty_overview():
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "healthy"
        assert client.get("/api/v1/overview").json()["is_empty"] is True

def test_event_is_costed_and_aggregated():
    payload = {"application":"SOC Copilot","provider":"local","model":"llama-3.1-70b","input_tokens":1000,"output_tokens":100,"latency_ms":250}
    with TestClient(app) as client:
        assert client.post("/api/v1/events", json=payload).status_code == 201
        data = client.get("/api/v1/overview").json()
        assert data["totals"]["requests"] == 1
        assert data["totals"]["tokens"] == 1100
        assert data["totals"]["spend"] > 0

def test_invalid_tokens_rejected():
    payload = {"application":"App","provider":"local","model":"test","input_tokens":-1}
    with TestClient(app) as client:
        assert client.post("/api/v1/events", json=payload).status_code == 422

def test_pricing_handles_cached_input():
    uncached = calculate("llama-3.1-8b", 1_000_000, 0, 0)[2]
    cached = calculate("llama-3.1-8b", 1_000_000, 0, 1_000_000)[2]
    assert cached < uncached

def test_analytics_groups_and_filters_events():
    with TestClient(app) as client:
        for application, department in (("App A","Engineering"),("App B","Finance")):
            client.post("/api/v1/events", json={"application":application,"department":department,"provider":"local","model":"llama-3.1-8b","input_tokens":100,"output_tokens":20})
        result=client.get("/api/v1/analytics?group_by=application&department=Engineering").json()
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "App A"
        assert result["items"][0]["total_tokens"] == 120

def test_custom_price_applies_to_future_event():
    price={"model_id":"private-model","provider":"Internal","input_price_per_million":2,"output_price_per_million":4,"cached_input_price_per_million":1,"currency":"USD","effective_date":"2026-08-30","last_verified":"2026-08-30","source":"Test"}
    with TestClient(app) as client:
        assert client.put("/api/v1/pricing/private-model",json=price).status_code == 200
        client.post("/api/v1/events",json={"application":"Private App","provider":"Internal","model":"private-model","input_tokens":1_000_000,"output_tokens":1_000_000})
        result=client.get("/api/v1/analytics?group_by=model").json()["items"][0]
        assert result["total_spend"] == 6

def test_csv_import_preview_and_commit():
    content="app,vendor,model_name,prompt_tokens,completion_tokens\nImported App,local,llama-3.1-8b,1000,200\nBroken,local,llama-3.1-8b,-1,20"
    payload={"format":"csv","content":content,"mapping":{}}
    with TestClient(app) as client:
        preview=client.post("/api/v1/import/preview",json=payload).json()
        assert preview["accepted"] == 1
        assert preview["rejected"] == 1
        committed=client.post("/api/v1/import",json=payload).json()
        assert committed["accepted"] == 1
        assert committed["rejected"] == 1

def test_forecast_refuses_insufficient_history():
    with TestClient(app) as client:
        client.post("/api/v1/events",json={"application":"New App","provider":"local","model":"llama-3.1-8b","input_tokens":100,"output_tokens":20})
        response=client.get("/api/v1/forecasts?metric=total_tokens&horizon=7")
        assert response.status_code == 422
        assert "at least 21" in response.json()["detail"]

def test_forecast_backtests_models_and_persists_run():
    with TestClient(app) as client:
        assert client.post("/api/v1/demo?days=30").status_code == 201
        response=client.get("/api/v1/forecasts?metric=total_tokens&horizon=7")
        assert response.status_code == 200
        result=response.json()
        assert result["selected_model"] in {"Naive","SeasonalNaive","AutoETS","AutoARIMA","Theta"}
        assert len(result["forecast"]) == 7
        assert result["summary"]["lower"] <= result["summary"]["upper"]
        assert len(result["backtests"]) >= 5
        assert client.get("/api/v1/forecasts/runs").json()[0]["forecast_id"] == result["forecast_id"]

def test_anomaly_detector_provides_baseline_evidence():
    points=[{"date":f"2026-08-{i+1:02d}","value":100} for i in range(10)]
    points[-1]["value"]=400
    result=detect({"Code Assistant":points})
    assert result[0]["severity"] in {"HIGH","CRITICAL"}
    assert result[0]["ratio"] == 4
    assert "baseline" in result[0]["evidence"]

def test_demo_produces_explainable_optimization_and_anomalies():
    with TestClient(app) as client:
        client.post("/api/v1/demo?days=30")
        optimization=client.get("/api/v1/optimization?days=30").json()
        assert optimization["summary"]["count"] > 0
        assert optimization["recommendations"][0]["labels"]["evidence"] == "OBSERVED"
        assert optimization["recommendations"][0]["labels"]["savings"] == "ESTIMATED"
        anomalies=client.get("/api/v1/anomalies?days=90").json()
        assert anomalies["method"].startswith("Trailing")
        assert len(anomalies["anomalies"]) > 0

def test_budget_crud_and_projection():
    payload={"name":"Engineering monthly","scope_type":"department","scope_value":"Engineering","period":"monthly","amount":100,"currency":"USD","active":True}
    with TestClient(app) as client:
        created=client.post("/api/v1/budgets",json=payload)
        assert created.status_code == 201
        budget=created.json()
        assert budget["projected_end_of_period"] >= 0
        assert budget["risk"] in {"LOW","MEDIUM","HIGH","CRITICAL"}
        assert client.get("/api/v1/budgets").json()["budgets"][0]["name"] == "Engineering monthly"
        assert client.delete(f"/api/v1/budgets/{budget['budget_id']}").status_code == 200

def test_organization_scenario_calculates_capacity_and_validates_mix():
    payload={"name":"Expected","employees":1000,"adoption_percent":50,"requests_per_user_day":10,"average_input_tokens":4000,"average_output_tokens":500,"working_days_month":20,"monthly_growth_percent":10,"cache_hit_percent":20,"retry_percent":5,"application_growth_percent":0,"model_mix":[{"model":"Economy","share_percent":70,"input_price_per_million":1,"output_price_per_million":2},{"model":"Premium","share_percent":30,"input_price_per_million":3,"output_price_per_million":10}]}
    with TestClient(app) as client:
        result=client.post("/api/v1/simulator/scenario",json=payload)
        assert result.status_code == 200
        data=result.json()
        assert data["active_ai_users"] == 500
        assert data["monthly_requests"] == 100_000
        assert data["monthly_attempts"] == 105_000
        assert data["annual_spend"] == data["monthly_spend"]*12
        payload["model_mix"][0]["share_percent"]=60
        assert client.post("/api/v1/simulator/scenario",json=payload).status_code == 422

def test_model_migration_uses_observed_volume_and_disclaims_quality():
    with TestClient(app) as client:
        client.post("/api/v1/demo?days=30")
        payload={"application":"Marketing Writer","alternative_model":"llama-3.1-8b","alternative_input_price_per_million":.1,"alternative_output_price_per_million":.1,"days":30}
        result=client.post("/api/v1/simulator/model-migration",json=payload)
        assert result.status_code == 200
        data=result.json()
        assert data["observed"]["requests"] > 0
        assert data["alternative"]["estimated_cost"] >= 0
        assert data["labels"]["current"] == "OBSERVED"
        assert "quality is not assumed equivalent" in data["disclaimer"]

def test_local_cloud_calculator_exposes_components_and_break_even():
    payload={"monthly_input_tokens":1_000_000_000,"monthly_output_tokens":200_000_000,"cloud_input_price_per_million":3,"cloud_output_price_per_million":12,"gpu_name":"GPU","gpu_quantity":2,"gpu_purchase_price":18000,"power_draw_watts":700,"electricity_rate_kwh":.15,"utilization_percent":55,"estimated_tokens_second":120,"hardware_life_months":36,"monthly_maintenance_cost":400,"monthly_hosting_cost":0}
    with TestClient(app) as client:
        result=client.post("/api/v1/simulator/local-vs-cloud",json=payload)
        assert result.status_code == 200
        data=result.json()
        assert data["cloud_monthly_cost"] == 5400
        assert data["components"]["hardware_amortization"] == 1000
        assert data["break_even_monthly_tokens"] > 0
        assert data["assumptions"]["quality_equivalence_assumed"] is False
