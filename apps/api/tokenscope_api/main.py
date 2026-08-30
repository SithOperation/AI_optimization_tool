from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Integer, case, delete, func, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .demo import generate_demo
from .importer import parse_import
from .models import Budget, ForecastRun, PriceOverride, TelemetryEvent
from .pricing import calculate, registry
from .schemas import BatchCreate, BudgetCreate, EventCreate, ImportRequest, PriceOverrideCreate
from services.forecasting.engine import METRICS, InsufficientHistory, explain_drivers, run_forecast
from services.anomaly.engine import detect
from services.optimizer.engine import recommendations

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield

app = FastAPI(title="TokenScope API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])

@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.headers.get("content-length") and int(request.headers["content-length"]) > 5_000_000:
        raise HTTPException(413, "Request body exceeds 5 MB")
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

def db_session():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def save_event(db: Session, payload: EventCreate):
    values = payload.model_dump()
    if db.get(TelemetryEvent, values["event_id"]):
        raise HTTPException(409, "event_id already exists")
    if values["estimated_total_cost"] is None:
        ci, co, total = calculate(values["model"], values["input_tokens"], values["output_tokens"], values["cached_input_tokens"], db)
        values.update(estimated_input_cost=ci, estimated_output_cost=co, estimated_total_cost=total)
    event = TelemetryEvent(**values)
    db.add(event)
    return event

@app.get("/api/v1/health")
def health(db: Session = Depends(db_session)):
    count = db.scalar(select(func.count()).select_from(TelemetryEvent)) or 0
    return {"status":"healthy", "database":"sqlite", "events":count, "privacy_mode":"metadata_only"}

@app.post("/api/v1/events", status_code=201)
def ingest(payload: EventCreate, db: Session = Depends(db_session)):
    event = save_event(db, payload); db.commit()
    return {"accepted":1, "event_id":event.event_id}

@app.post("/api/v1/events/batch", status_code=201)
def ingest_batch(payload: BatchCreate, db: Session = Depends(db_session)):
    ids = [save_event(db, item).event_id for item in payload.events]; db.commit()
    return {"accepted":len(ids), "event_ids":ids}

@app.post("/api/v1/demo", status_code=201)
def create_demo(days: int = Query(30, ge=7, le=90), db: Session = Depends(db_session)):
    existing = db.scalar(select(func.count()).select_from(TelemetryEvent).where(TelemetryEvent.source == "demo")) or 0
    if existing: return {"created":0, "existing":existing}
    created=generate_demo(db, days)
    if not db.scalar(select(func.count()).select_from(Budget)):
        db.add(Budget(name="Monthly AI operations",scope_type="organization",period="monthly",amount=4.0,currency="USD"));db.commit()
    return {"created":created}

@app.delete("/api/v1/demo")
def clear_demo(db: Session = Depends(db_session)):
    result = db.execute(delete(TelemetryEvent).where(TelemetryEvent.source == "demo")); db.commit()
    return {"deleted":result.rowcount}

@app.get("/api/v1/overview")
def overview(days: int = Query(30, ge=1, le=365), db: Session = Depends(db_session)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    where = TelemetryEvent.timestamp >= since
    totals = db.execute(select(func.count(), func.coalesce(func.sum(TelemetryEvent.total_tokens),0), func.coalesce(func.sum(TelemetryEvent.estimated_total_cost),0), func.coalesce(func.avg(TelemetryEvent.latency_ms),0), func.coalesce(func.sum(func.cast(TelemetryEvent.success == False, Integer)),0)).where(where)).one()
    by_model = db.execute(select(TelemetryEvent.model, func.count(), func.sum(TelemetryEvent.total_tokens), func.sum(TelemetryEvent.estimated_total_cost)).where(where).group_by(TelemetryEvent.model).order_by(func.sum(TelemetryEvent.total_tokens).desc())).all()
    by_app = db.execute(select(TelemetryEvent.application, TelemetryEvent.department, func.count(), func.sum(TelemetryEvent.total_tokens), func.sum(TelemetryEvent.estimated_total_cost)).where(where).group_by(TelemetryEvent.application, TelemetryEvent.department).order_by(func.sum(TelemetryEvent.total_tokens).desc())).all()
    series = db.execute(select(func.date(TelemetryEvent.timestamp), func.count(), func.sum(TelemetryEvent.total_tokens), func.sum(TelemetryEvent.estimated_total_cost)).where(where).group_by(func.date(TelemetryEvent.timestamp)).order_by(func.date(TelemetryEvent.timestamp))).all()
    requests, tokens, spend, latency, failures = totals
    return {"period_days":days,"is_empty":requests==0,"is_demo":bool(db.scalar(select(func.count()).select_from(TelemetryEvent).where(TelemetryEvent.source=="demo"))),"totals":{"requests":requests,"tokens":tokens,"spend":round(spend,4),"average_latency_ms":round(latency,1),"success_rate":round((requests-failures)/requests*100,2) if requests else 0},"models":[{"model":r[0],"requests":r[1],"tokens":r[2],"spend":round(r[3],4)} for r in by_model],"applications":[{"application":r[0],"department":r[1],"requests":r[2],"tokens":r[3],"spend":round(r[4],4)} for r in by_app],"timeseries":[{"date":r[0],"requests":r[1],"tokens":r[2],"spend":round(r[3],4)} for r in series]}

FILTER_FIELDS = {"provider":TelemetryEvent.provider,"model":TelemetryEvent.model,"department":TelemetryEvent.department,"team":TelemetryEvent.team,"application":TelemetryEvent.application,"workload":TelemetryEvent.workload}

def filters_for(days, provider=None, model=None, department=None, team=None, application=None, workload=None):
    clauses=[TelemetryEvent.timestamp >= datetime.now(timezone.utc)-timedelta(days=days)]
    for name,value in locals().copy().items():
        if name in FILTER_FIELDS and value: clauses.append(FILTER_FIELDS[name] == value)
    return clauses

@app.get("/api/v1/filters")
def filter_options(db: Session = Depends(db_session)):
    return {name:[row[0] for row in db.execute(select(column).distinct().where(column.is_not(None)).order_by(column)).all()] for name,column in FILTER_FIELDS.items()}

@app.get("/api/v1/analytics")
def analytics(group_by: str = Query("application", pattern="^(provider|model|department|team|application|workload|day|hour)$"), days: int = Query(30, ge=1, le=365), provider: str|None=None, model: str|None=None, department: str|None=None, team: str|None=None, application: str|None=None, workload: str|None=None, db: Session = Depends(db_session)):
    clauses=filters_for(days,provider,model,department,team,application,workload)
    dimension=func.date(TelemetryEvent.timestamp) if group_by=="day" else (func.strftime("%H:00",TelemetryEvent.timestamp) if group_by=="hour" else FILTER_FIELDS[group_by])
    rows=db.execute(select(dimension.label("name"),func.count(),func.sum(func.cast(TelemetryEvent.success==True,Integer)),func.sum(TelemetryEvent.input_tokens),func.sum(TelemetryEvent.output_tokens),func.sum(TelemetryEvent.cached_input_tokens),func.sum(TelemetryEvent.reasoning_tokens),func.sum(TelemetryEvent.total_tokens),func.avg(TelemetryEvent.total_tokens),func.sum(TelemetryEvent.estimated_input_cost),func.sum(TelemetryEvent.estimated_output_cost),func.sum(TelemetryEvent.estimated_total_cost)).where(*clauses).group_by(dimension).order_by(func.sum(TelemetryEvent.total_tokens).desc())).all()
    items=[{"name":r[0] or "Unassigned","requests":r[1],"successful_requests":r[2] or 0,"failed_requests":r[1]-(r[2] or 0),"input_tokens":r[3] or 0,"output_tokens":r[4] or 0,"cached_tokens":r[5] or 0,"reasoning_tokens":r[6] or 0,"total_tokens":r[7] or 0,"average_tokens_per_request":round(r[8] or 0,1),"input_spend":round(r[9] or 0,4),"output_spend":round(r[10] or 0,4),"total_spend":round(r[11] or 0,4),"cost_per_request":round((r[11] or 0)/r[1],6) if r[1] else 0,"cost_per_successful_request":round((r[11] or 0)/(r[2] or 1),6)} for r in rows]
    return {"group_by":group_by,"period_days":days,"filters":{"provider":provider,"model":model,"department":department,"team":team,"application":application,"workload":workload},"items":items}

@app.get("/api/v1/pricing")
def pricing_registry(db: Session = Depends(db_session)):
    return {"version":"2026.08.1","prices":registry(db),"notice":"Bundled prices are estimates. Configure overrides for negotiated or local costs."}

@app.put("/api/v1/pricing/{model_id}")
def set_price(model_id: str, payload: PriceOverrideCreate, db: Session = Depends(db_session)):
    if payload.model_id != model_id: raise HTTPException(400,"model_id must match the URL")
    values=payload.model_dump(); values["model_id"]=model_id.lower()
    existing=db.get(PriceOverride,model_id.lower())
    if existing:
        for key,value in values.items(): setattr(existing,key,value)
    else: db.add(PriceOverride(**values))
    db.commit(); return {"saved":model_id.lower(),"applies_to":"future events"}

@app.delete("/api/v1/pricing/{model_id}")
def delete_price(model_id: str, db: Session = Depends(db_session)):
    existing=db.get(PriceOverride,model_id.lower())
    if not existing: raise HTTPException(404,"Custom price not found")
    db.delete(existing);db.commit();return {"deleted":model_id.lower()}

@app.post("/api/v1/import/preview")
def preview_import(payload: ImportRequest):
    try: mapping,accepted,rejected=parse_import(payload)
    except (ValueError,TypeError) as error: raise HTTPException(400,str(error)) from error
    return {"mapping":mapping,"accepted":len(accepted),"rejected":len(rejected),"preview":[item.model_dump(mode="json") for item in accepted[:5]],"errors":rejected[:50]}

@app.post("/api/v1/import", status_code=201)
def commit_import(payload: ImportRequest, db: Session = Depends(db_session)):
    try: mapping,accepted,rejected=parse_import(payload)
    except (ValueError,TypeError) as error: raise HTTPException(400,str(error)) from error
    ids=[]
    for item in accepted:
        item.source="import"; ids.append(save_event(db,item).event_id)
    db.commit();return {"accepted":len(ids),"rejected":len(rejected),"event_ids":ids,"errors":rejected[:50],"mapping":mapping}

FORECAST_METRICS={"requests":func.count(),"input_tokens":func.sum(TelemetryEvent.input_tokens),"output_tokens":func.sum(TelemetryEvent.output_tokens),"total_tokens":func.sum(TelemetryEvent.total_tokens),"spend":func.sum(TelemetryEvent.estimated_total_cost)}

@app.get("/api/v1/forecasts")
def forecast(metric: str = Query("total_tokens"), horizon: int = Query(30), training_days: int = Query(180, ge=21, le=730), provider: str|None=None, model: str|None=None, department: str|None=None, team: str|None=None, application: str|None=None, workload: str|None=None, db: Session = Depends(db_session)):
    if metric not in METRICS: raise HTTPException(400,f"metric must be one of {sorted(METRICS)}")
    if horizon not in (7,30,90,365): raise HTTPException(400,"horizon must be 7, 30, 90, or 365 days")
    clauses=filters_for(training_days,provider,model,department,team,application,workload); expression=FORECAST_METRICS[metric]
    rows=db.execute(select(func.date(TelemetryEvent.timestamp),expression).where(*clauses).group_by(func.date(TelemetryEvent.timestamp)).order_by(func.date(TelemetryEvent.timestamp))).all()
    if not rows: raise HTTPException(422,"More historical data is needed for a reliable forecast. No observations match these filters.")
    start=datetime.fromisoformat(rows[0][0]).date();end=datetime.fromisoformat(rows[-1][0]).date();lookup={row[0]:float(row[1] or 0) for row in rows};dates=[];values=[];cursor=start
    while cursor<=end:
        key=cursor.isoformat();dates.append(key);values.append(lookup.get(key,0));cursor+=timedelta(days=1)
    app_rows=db.execute(select(TelemetryEvent.application,expression).where(*clauses).group_by(TelemetryEvent.application).order_by(expression.desc())).all()
    applications=[{"name":row[0],"value":float(row[1] or 0)} for row in app_rows]
    try: result=run_forecast(dates,values,horizon)
    except InsufficientHistory as error: raise HTTPException(422,str(error)) from error
    drivers=explain_drivers([{"date":d,"value":v} for d,v in zip(dates,values)],applications)
    run=ForecastRun(metric=metric,horizon_days=horizon,selected_model=result["selected_model"],training_start=dates[0],training_end=dates[-1],training_points=len(values),error_value=result["error_value"],backtest_results=result["backtests"],history_values=[{"date":d,"value":v} for d,v in zip(dates,values)],forecast_values=result["values"],drivers=drivers)
    db.add(run);db.commit()
    expected_total=sum(x["expected"] for x in result["values"]);lower_total=sum(x["lower"] for x in result["values"]);upper_total=sum(x["upper"] for x in result["values"])
    return {"forecast_id":run.forecast_id,"metric":metric,"horizon_days":horizon,"created_at":run.created_at,"training":{"start":dates[0],"end":dates[-1],"points":len(values)},"selected_model":result["selected_model"],"accuracy":{"metric":"sMAPE","value":result["error_value"]},"backtests":result["backtests"],"history":run.history_values,"forecast":result["values"],"summary":{"expected":expected_total,"lower":lower_total,"upper":upper_total},"drivers":drivers,"language":{"expected":"Historical statistical estimate","interval":"95% prediction interval","guarantee":False}}

@app.get("/api/v1/forecasts/runs")
def forecast_runs(limit: int = Query(20,ge=1,le=100), db: Session = Depends(db_session)):
    rows=db.execute(select(ForecastRun).order_by(ForecastRun.created_at.desc()).limit(limit)).scalars().all()
    return [{"forecast_id":r.forecast_id,"created_at":r.created_at,"metric":r.metric,"horizon_days":r.horizon_days,"selected_model":r.selected_model,"error_metric":r.error_metric,"error_value":r.error_value,"training_points":r.training_points} for r in rows]

@app.get("/api/v1/anomalies")
def anomalies(days: int = Query(90,ge=14,le=365), limit: int = Query(30,ge=1,le=100), db: Session = Depends(db_session)):
    clauses=filters_for(days)
    rows=db.execute(select(TelemetryEvent.application,func.date(TelemetryEvent.timestamp),func.sum(TelemetryEvent.total_tokens)).where(*clauses).group_by(TelemetryEvent.application,func.date(TelemetryEvent.timestamp)).order_by(TelemetryEvent.application,func.date(TelemetryEvent.timestamp))).all()
    grouped={}
    for application,date,value in rows: grouped.setdefault(application,[]).append({"date":date,"value":value or 0})
    findings=detect(grouped,limit)
    return {"period_days":days,"anomalies":findings,"counts":{level:sum(x["severity"]==level for x in findings) for level in ("CRITICAL","HIGH","MEDIUM","LOW","INFO")},"method":"Trailing 28-day baseline with ratio and z-score thresholds"}

@app.get("/api/v1/optimization")
def optimization(days: int = Query(30,ge=7,le=365), db: Session = Depends(db_session)):
    clauses=filters_for(days)
    rows=db.execute(select(TelemetryEvent.application,TelemetryEvent.model,func.count(),func.sum(TelemetryEvent.estimated_total_cost),func.sum(TelemetryEvent.input_tokens),func.sum(TelemetryEvent.estimated_input_cost),func.avg(func.coalesce(TelemetryEvent.context_utilization,0)),func.sum(case((TelemetryEvent.retry_count>0,1),else_=0)),func.sum(case((TelemetryEvent.retry_count>0,TelemetryEvent.estimated_total_cost),else_=0)),func.sum(case((TelemetryEvent.success==False,1),else_=0)),func.sum(case((TelemetryEvent.success==False,TelemetryEvent.estimated_total_cost),else_=0)),func.sum(case((TelemetryEvent.cache_hit==True,1),else_=0)),func.sum(TelemetryEvent.output_tokens)).where(*clauses).group_by(TelemetryEvent.application,TelemetryEvent.model)).all()
    apps=[]
    for r in rows:
        requests=r[2] or 1;output=r[12] or 1
        apps.append({"application":r[0],"model":r[1],"requests":requests,"spend":r[3] or 0,"input_tokens":r[4] or 0,"input_spend":r[5] or 0,"context_utilization":r[6] or 0,"retry_rate":(r[7] or 0)/requests,"retry_spend":r[8] or 0,"failure_rate":(r[9] or 0)/requests,"failed_spend":r[10] or 0,"cache_rate":(r[11] or 0)/requests,"input_output_ratio":(r[4] or 0)/output})
    items=recommendations(apps,days)
    return {"period_days":days,"recommendations":items,"summary":{"count":len(items),"estimated_monthly_savings":round(sum(x["estimated_monthly_savings"] for x in items),2)},"method":"Deterministic threshold rules over observed metadata; no LLM used"}

def budget_scope_clause(budget):
    if budget.scope_type=="organization": return None
    return FILTER_FIELDS[budget.scope_type] == budget.scope_value

def budget_status(budget,db):
    now=datetime.now(timezone.utc); months={"monthly":1,"quarterly":3,"annual":12}[budget.period]
    start_month=((now.month-1)//months)*months+1; start=datetime(now.year,start_month,1,tzinfo=timezone.utc)
    if start_month+months>12: end=datetime(now.year+1,(start_month+months)%12,1,tzinfo=timezone.utc)
    else: end=datetime(now.year,start_month+months,1,tzinfo=timezone.utc)
    clauses=[TelemetryEvent.timestamp>=start,TelemetryEvent.timestamp<end];scope=budget_scope_clause(budget)
    if scope is not None: clauses.append(scope)
    spent=float(db.scalar(select(func.coalesce(func.sum(TelemetryEvent.estimated_total_cost),0)).where(*clauses)) or 0)
    elapsed=max((now-start).total_seconds()/86400,1);period_days=(end-start).days;daily=spent/elapsed;projected=daily*period_days;remaining=max(0,budget.amount-spent)
    exhaustion=(start+timedelta(days=budget.amount/daily)).date().isoformat() if daily>0 and projected>budget.amount else None
    ratio=projected/budget.amount
    risk="CRITICAL" if ratio>=1.25 else "HIGH" if ratio>=1 else "MEDIUM" if ratio>=.85 else "LOW"
    return {"budget_id":budget.budget_id,"name":budget.name,"scope_type":budget.scope_type,"scope_value":budget.scope_value,"period":budget.period,"amount":budget.amount,"currency":budget.currency,"spent":round(spent,4),"remaining":round(remaining,4),"used_percent":round(spent/budget.amount*100,1),"projected_end_of_period":round(projected,4),"risk":risk,"estimated_exhaustion_date":exhaustion,"period_start":start.date().isoformat(),"period_end":(end-timedelta(days=1)).date().isoformat(),"active":budget.active}

@app.get("/api/v1/budgets")
def list_budgets(db: Session = Depends(db_session)):
    return {"budgets":[budget_status(row,db) for row in db.execute(select(Budget).order_by(Budget.created_at)).scalars().all()]}

@app.post("/api/v1/budgets",status_code=201)
def create_budget(payload: BudgetCreate, db: Session = Depends(db_session)):
    budget=Budget(**payload.model_dump());db.add(budget);db.commit();return budget_status(budget,db)

@app.delete("/api/v1/budgets/{budget_id}")
def delete_budget(budget_id: str, db: Session = Depends(db_session)):
    budget=db.get(Budget,budget_id)
    if not budget: raise HTTPException(404,"Budget not found")
    db.delete(budget);db.commit();return {"deleted":budget_id}
