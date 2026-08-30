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
