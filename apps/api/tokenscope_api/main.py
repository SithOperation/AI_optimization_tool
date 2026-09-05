from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
import asyncio
import csv
import httpx
import io
import json
import logging
import os
import secrets
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Integer, case, delete, func, select
from sqlalchemy.orm import Session

from .database import Base, DEFAULT_DB, SessionLocal, engine
from .app_config import APP_NAME, VERSION, application_data_dir, build_information, configure_logging, ensure_application_directories
from .demo import generate_demo
from .importer import parse_import
from .importer_streaming import StreamingImporter, cleanup_stale_import_files, export_rejected_rows_csv
from .models import AppSetting, AuditEvent, Budget, CloudProviderConfig, ForecastRun, ImportJob, Integration, ModelEvaluation, PriceOverride, TelemetryEvent
from .pricing import calculate, get_price, registry
from .schemas import AdapterEvent, BatchCreate, BudgetCreate, CloudProviderRequest, EventCreate, FileUploadStart, ImportCommit, ImportHistoryItem, ImportJobStatus, ImportRequest, ImportPreview, IntegrationRequest, LocalCloudRequest, MigrationRequest, ModelEvaluationCreate, PriceOverrideCreate, PrivacyRequest, RetentionRequest, ScenarioRequest
from services.forecasting.engine import METRICS, InsufficientHistory, explain_drivers, run_forecast
from services.anomaly.engine import detect
from services.optimizer.engine import recommendations
from services.simulator.engine import local_vs_cloud, organization_scenario
from integrations.litellm.adapter import normalize_litellm
from integrations.openai_compatible.adapter import normalize_response
from integrations.opentelemetry.adapter import normalize_otlp
from integrations.security import validate_local_url
from services.security.rate_limit import SlidingWindowLimiter
from services.analytics.efficiency import efficiency_score

@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    paths = ensure_application_directories()
    Base.metadata.create_all(engine)
    cleanup_stale_import_files()
    with SessionLocal() as startup_db:
        telemetry_count = startup_db.scalar(select(func.count()).select_from(TelemetryEvent)) or 0
    application_logger = logging.getLogger("aiopt.application")
    application_logger.info("TokenScope data directory: %s", application_data_dir())
    application_logger.info("TokenScope database: %s", DEFAULT_DB)
    application_logger.info("Telemetry records: %s", telemetry_count)
    yield
    engine.dispose()

desktop_runtime = os.getenv("AIOPT_RUNTIME") == "desktop"
app = FastAPI(title=f"{APP_NAME} API", version=VERSION, lifespan=lifespan,
              docs_url=None if desktop_runtime else "/docs",
              redoc_url=None if desktop_runtime else "/redoc",
              openapi_url=None if desktop_runtime else "/openapi.json")
desktop_origins = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"]
development_origins = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(CORSMiddleware, allow_origins=desktop_origins if desktop_runtime else desktop_origins + development_origins, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "X-TokenScope-Key"])

@app.exception_handler(RequestValidationError)
async def controlled_validation_error(_: Request, error: RequestValidationError):
    details = [{key: value for key, value in item.items() if key not in {"input", "ctx"}} for item in error.errors()]
    return JSONResponse({"detail": details}, status_code=422)
rate_limiter=SlidingWindowLimiter(limit=int(os.getenv("TOKENSCOPE_INGEST_RATE_LIMIT","600")))
logger=logging.getLogger("aiopt.api")
if not logger.handlers:
    handler=logging.StreamHandler();handler.setFormatter(logging.Formatter('%(message)s'));logger.addHandler(handler);logger.setLevel(logging.INFO)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Allow large files for import endpoints (up to 500 MB), but enforce 5 MB limit for normal API
    is_import_upload = request.url.path.startswith("/api/v1/import/") and "/upload" in request.url.path
    max_size = 6_000_000 if is_import_upload else 5_000_000
    content_length = request.headers.get("content-length")
    try:
        declared_size = int(content_length) if content_length is not None else None
    except ValueError:
        return JSONResponse({"detail":"Invalid Content-Length header"},status_code=400)
    if declared_size is not None and (declared_size < 0 or declared_size > max_size):
        return JSONResponse({"detail":f"Request body exceeds {max_size / 1_000_000:.0f} MB"},status_code=413)
    if request.method in {"POST", "PUT", "PATCH"} and declared_size is None:
        return JSONResponse({"detail":"Content-Length is required"},status_code=411)
    ingestion_paths=("/api/v1/events","/api/v1/otlp/","/api/v1/integrations/litellm/events","/api/v1/integrations/compatible/events")
    is_ingestion = request.method == "POST" and any(request.url.path.startswith(path) for path in ingestion_paths)
    configured_key=os.getenv("TOKENSCOPE_API_KEY")
    desktop_key=os.getenv("AIOPT_DESKTOP_TOKEN")
    is_health = request.url.path == "/api/v1/health"
    requires_auth = bool(
        (configured_key and not is_health)
        or (desktop_key and (is_health or (request.method != "GET" and not is_ingestion)))
    )
    if requires_auth and request.url.path.startswith("/api/v1"):
        supplied_key = request.headers.get("X-TokenScope-Key", "")
        valid_key = any(secrets.compare_digest(supplied_key, candidate) for candidate in (configured_key, desktop_key) if candidate)
        if not valid_key:
            return JSONResponse({"detail":"Authentication required"},status_code=401)
    if is_ingestion:
        client=request.client.host if request.client else "unknown"
        if not rate_limiter.allow(client): return JSONResponse({"detail":"Ingestion rate limit exceeded"},status_code=429,headers={"Retry-After":"60"})
    started=datetime.now(timezone.utc)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    logger.info(json.dumps({"timestamp":started.isoformat(),"method":request.method,"path":request.url.path,"status":response.status_code,"duration_ms":round((datetime.now(timezone.utc)-started).total_seconds()*1000,2)}))
    return response

def db_session():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def audit(db,action,target_type,target_id=None,**details):
    db.add(AuditEvent(action=action,target_type=target_type,target_id=target_id,details=details))

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

TELEMETRY_RESET_MODELS = (
    ("forecast_runs", ForecastRun),
    ("import_jobs", ImportJob),
    ("telemetry_events", TelemetryEvent),
)

def clear_telemetry_data(db: Session, reset_models=TELEMETRY_RESET_MODELS):
    deleted = {}
    try:
        for key, model in reset_models:
            result = db.execute(delete(model))
            deleted[key] = result.rowcount or 0
        audit(db, "telemetry.cleared", "telemetry", details_deleted=deleted)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"success": True, "deleted": deleted}

def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

@app.get("/api/v1/health")
def health(db: Session = Depends(db_session)):
    count = db.scalar(select(func.count()).select_from(TelemetryEvent)) or 0
    return {"status":"healthy", "database":"sqlite", "events":count, "privacy_mode":"metadata_only", "services":{name:{"status":"Healthy","checked":True} for name in ("application","api","database","telemetry_receiver","forecast_engine")}}

@app.get("/api/v1/application")
def application_status(db: Session = Depends(db_session)):
    setup=db.get(AppSetting,"first_run");mode=db.get(AppSetting,"user_mode");info=build_information()
    info.update({"first_run_complete":bool(setup and setup.value.get("complete")),"mode":mode.value.get("mode","Operations") if mode else "Operations","data_directory":str(application_data_dir()),"local_first":True})
    return info

@app.put("/api/v1/application/setup")
def complete_setup(payload: dict, db: Session = Depends(db_session)):
    choice=payload.get("choice")
    if choice not in {"demo","local","telemetry","import","advanced"}: raise HTTPException(422,"Invalid setup choice")
    privacy=PrivacyRequest(**payload.get("privacy",{})).model_dump()
    for key,value in (("privacy",privacy),("first_run",{"complete":True,"choice":choice,"completed_at":datetime.now(timezone.utc).isoformat()})):
        row=db.get(AppSetting,key)
        if row: row.value=value
        else: db.add(AppSetting(key=key,value=value))
    if choice=="demo" and not db.scalar(select(func.count()).select_from(TelemetryEvent).where(TelemetryEvent.source=="demo")): generate_demo(db,30)
    db.commit();return {"complete":True,"choice":choice}

@app.delete("/api/v1/application/setup")
def reset_setup(db: Session = Depends(db_session)):
    db.execute(delete(AppSetting).where(AppSetting.key=="first_run"));db.commit();return {"complete":False}

@app.put("/api/v1/application/mode")
def set_mode(payload: dict, db: Session = Depends(db_session)):
    mode=payload.get("mode")
    if mode not in {"Executive","Operations","Engineering"}: raise HTTPException(422,"Invalid application mode")
    row=db.get(AppSetting,"user_mode")
    if row: row.value={"mode":mode}
    else: db.add(AppSetting(key="user_mode",value={"mode":mode}))
    db.commit();return {"mode":mode}

@app.get("/api/v1/integrations/detect-local")
async def detect_local_services():
    targets=[("Ollama","http://127.0.0.1:11434/api/tags"),("vLLM","http://127.0.0.1:8001/v1/models"),("LiteLLM","http://127.0.0.1:4000/health"),("OpenTelemetry","http://127.0.0.1:4318/")]
    async def check(name,url):
        try:
            async with httpx.AsyncClient(timeout=.6) as client: response=await client.get(url)
            detected=response.status_code<500
        except (httpx.HTTPError,OSError): detected=False
        return {"name":name,"url":url,"status":"Detected" if detected else "Not detected"}
    return {"services":await asyncio.gather(*(check(*target) for target in targets)),"scope":"localhost only","auto_connected":False}

@app.post("/api/v1/events", status_code=201)
def ingest(payload: EventCreate, db: Session = Depends(db_session)):
    event = save_event(db, payload); db.commit()
    return {"accepted":1, "event_id":event.event_id}

@app.post("/api/v1/events/batch", status_code=201)
def ingest_batch(payload: BatchCreate, db: Session = Depends(db_session)):
    ids = [save_event(db, item).event_id for item in payload.events]; db.commit()
    return {"accepted":len(ids), "event_ids":ids}

@app.delete("/api/v1/telemetry")
def clear_telemetry(db: Session = Depends(db_session)):
    return clear_telemetry_data(db)

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
    audit(db,"pricing.override_saved","pricing",model_id.lower());db.commit(); return {"saved":model_id.lower(),"applies_to":"future events"}

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
    budget=Budget(**payload.model_dump());db.add(budget);db.flush();audit(db,"budget.created","budget",budget.budget_id,scope_type=budget.scope_type);db.commit();return budget_status(budget,db)

@app.delete("/api/v1/budgets/{budget_id}")
def delete_budget(budget_id: str, db: Session = Depends(db_session)):
    budget=db.get(Budget,budget_id)
    if not budget: raise HTTPException(404,"Budget not found")
    db.delete(budget);db.commit();return {"deleted":budget_id}

@app.post("/api/v1/simulator/scenario")
def simulate_scenario(payload: ScenarioRequest):
    try: result=organization_scenario(payload)
    except ValueError as error: raise HTTPException(422,str(error)) from error
    return {**result,"labels":{"inputs":"USER-SUPPLIED ASSUMPTIONS","outputs":"CALCULATED","quality":"NOT EVALUATED"}}

@app.post("/api/v1/simulator/model-migration")
def simulate_migration(payload: MigrationRequest, db: Session = Depends(db_session)):
    since=datetime.now(timezone.utc)-timedelta(days=payload.days)
    row=db.execute(select(TelemetryEvent.model,func.count(),func.sum(TelemetryEvent.input_tokens),func.sum(TelemetryEvent.output_tokens),func.sum(TelemetryEvent.cached_input_tokens),func.sum(TelemetryEvent.estimated_total_cost)).where(TelemetryEvent.timestamp>=since,TelemetryEvent.application==payload.application).group_by(TelemetryEvent.model).order_by(func.count().desc())).first()
    if not row: raise HTTPException(404,"No observed telemetry found for this application and period")
    current_model,requests,input_tokens,output_tokens,cached_tokens,current_cost=row
    alternative=get_price(payload.alternative_model,db)
    input_price=payload.alternative_input_price_per_million if payload.alternative_input_price_per_million is not None else alternative.input
    output_price=payload.alternative_output_price_per_million if payload.alternative_output_price_per_million is not None else alternative.output
    alternative_cost=((input_tokens-cached_tokens)*input_price+cached_tokens*alternative.cached+output_tokens*output_price)/1_000_000
    savings=(current_cost or 0)-alternative_cost
    return {"application":payload.application,"period_days":payload.days,"observed":{"model":current_model,"requests":requests,"input_tokens":input_tokens,"output_tokens":output_tokens,"cached_input_tokens":cached_tokens,"cost":round(current_cost or 0,4)},"alternative":{"model":payload.alternative_model,"input_price_per_million":input_price,"output_price_per_million":output_price,"estimated_cost":round(alternative_cost,4)},"estimated_savings":round(savings,4),"estimated_annual_savings":round(savings*(365/payload.days),4),"disclaimer":"Cost comparison only. Output quality is not assumed equivalent.","labels":{"current":"OBSERVED","alternative":"ESTIMATED","quality":"NOT EVALUATED"}}

@app.post("/api/v1/simulator/local-vs-cloud")
def simulate_local_cloud(payload: LocalCloudRequest):
    return {**local_vs_cloud(payload),"disclaimer":"Infrastructure cost estimate only. Throughput, reliability, operations, and output quality assumptions require validation.","labels":{"inputs":"USER-SUPPLIED ASSUMPTIONS","outputs":"ESTIMATED","quality":"NOT EVALUATED"}}

INTEGRATION_CATALOG=[
    {"kind":"opentelemetry","name":"OpenTelemetry","description":"Receive OTLP/HTTP JSON GenAI spans","optional":False,"endpoint":"/api/v1/otlp/v1/traces"},
    {"kind":"litellm","name":"LiteLLM","description":"Receive success/failure callback payloads","optional":True,"default_url":"http://localhost:4000"},
    {"kind":"ollama","name":"Ollama","description":"Discover local Ollama models and accept response usage","optional":True,"default_url":"http://localhost:11434"},
    {"kind":"vllm","name":"vLLM","description":"Connect to a local OpenAI-compatible vLLM server","optional":True,"default_url":"http://localhost:8001"},
    {"kind":"generic-openai-compatible","name":"OpenAI-compatible","description":"Connect any local compatible endpoint","optional":True,"default_url":"http://localhost:8080"},
]

def integration_dict(row):
    return {"integration_id":row.integration_id,"kind":row.kind,"name":row.name,"base_url":row.base_url,"enabled":row.enabled,"collect_user_identifiers":row.collect_user_identifiers,"status":row.status,"last_checked_at":row.last_checked_at,"created_at":row.created_at}

def check_endpoint(kind,url):
    safe=validate_local_url(url); path="/api/tags" if kind=="ollama" else "/v1/models"
    try:
        response=httpx.get(safe+path,timeout=2.5);response.raise_for_status();body=response.json()
        models=[item.get("name") or item.get("id") for item in body.get("models",body.get("data",[])) if item.get("name") or item.get("id")]
        return {"reachable":True,"status_code":response.status_code,"models":models[:50],"checked_url":safe+path}
    except (httpx.HTTPError,ValueError) as error:
        return {"reachable":False,"error":f"{type(error).__name__}: {error}","checked_url":safe+path}

@app.get("/api/v1/integrations")
def integrations_list(db: Session = Depends(db_session)):
    configured=[integration_dict(row) for row in db.execute(select(Integration).order_by(Integration.created_at)).scalars().all()]
    return {"catalog":INTEGRATION_CATALOG,"configured":configured,"privacy_default":"User identifiers are disabled","commercial_providers":"Optional — not required for TokenScope"}

@app.post("/api/v1/integrations/test")
def test_integration(payload: IntegrationRequest):
    try: return check_endpoint(payload.kind,payload.base_url)
    except ValueError as error: raise HTTPException(400,str(error)) from error

@app.post("/api/v1/integrations",status_code=201)
def configure_integration(payload: IntegrationRequest, db: Session = Depends(db_session)):
    try: url=validate_local_url(payload.base_url)
    except ValueError as error: raise HTTPException(400,str(error)) from error
    row=Integration(kind=payload.kind,name=payload.name,base_url=url,collect_user_identifiers=payload.collect_user_identifiers,status="configured")
    db.add(row);db.flush();audit(db,"integration.configured","integration",row.integration_id,kind=row.kind);db.commit();return integration_dict(row)

@app.delete("/api/v1/integrations/{integration_id}")
def remove_integration(integration_id: str, db: Session = Depends(db_session)):
    row=db.get(Integration,integration_id)
    if not row: raise HTTPException(404,"Integration not found")
    audit(db,"integration.removed","integration",integration_id,kind=row.kind);db.delete(row);db.commit();return {"deleted":integration_id}

@app.post("/api/v1/integrations/compatible/events",status_code=201)
def compatible_event(payload: AdapterEvent, db: Session = Depends(db_session)):
    event=save_event(db,EventCreate.model_validate(normalize_response(payload)));db.commit();return {"accepted":1,"event_id":event.event_id}

@app.post("/api/v1/integrations/litellm/events",status_code=201)
def litellm_event(payload: dict, db: Session = Depends(db_session)):
    event=save_event(db,EventCreate.model_validate(normalize_litellm(payload,False)));db.commit();return {"accepted":1,"event_id":event.event_id}

@app.post("/api/v1/otlp/v1/traces",status_code=201)
def otlp_traces(payload: dict, db: Session = Depends(db_session)):
    normalized,errors=normalize_otlp(payload);ids=[]
    for item in normalized:
        try: ids.append(save_event(db,EventCreate.model_validate(item)).event_id)
        except (ValueError,HTTPException) as error: errors.append({"span_id":item.get("event_id"),"reason":str(error)})
    db.commit();return {"accepted":len(ids),"rejected":len(errors),"event_ids":ids,"errors":errors[:50]}

CLOUD_CATALOG=[
    {"provider":"openai","name":"OpenAI","default_env_var":"OPENAI_API_KEY"},
    {"provider":"anthropic","name":"Anthropic","default_env_var":"ANTHROPIC_API_KEY"},
    {"provider":"gemini","name":"Google Gemini","default_env_var":"GEMINI_API_KEY"},
    {"provider":"azure-openai","name":"Azure OpenAI","default_env_var":"AZURE_OPENAI_API_KEY"},
    {"provider":"bedrock","name":"AWS Bedrock","default_env_var":"AWS_ACCESS_KEY_ID"},
]

def cloud_dict(row):
    return {"provider":row.provider,"enabled":row.enabled,"credential_env_var":row.credential_env_var,"credential_available":bool(os.getenv(row.credential_env_var)),"endpoint":row.endpoint,"updated_at":row.updated_at,"secret_stored":False}

@app.get("/api/v1/cloud-providers")
def cloud_providers(db: Session = Depends(db_session)):
    configured={row.provider:cloud_dict(row) for row in db.execute(select(CloudProviderConfig)).scalars().all()}
    return {"catalog":[{**item,"configuration":configured.get(item["provider"]),"optional":True,"notice":"Optional — not required for TokenScope"} for item in CLOUD_CATALOG],"secrets_policy":"Credential values are read from environment variables and never stored in the database."}

@app.put("/api/v1/cloud-providers/{provider}")
def configure_cloud_provider(provider: str, payload: CloudProviderRequest, db: Session = Depends(db_session)):
    if provider!=payload.provider: raise HTTPException(400,"provider must match the URL")
    if payload.endpoint:
        parsed=urlparse(payload.endpoint)
        if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password: raise HTTPException(400,"Provider endpoints must use HTTPS without embedded credentials")
    row=db.get(CloudProviderConfig,provider)
    if row:
        row.enabled=payload.enabled;row.credential_env_var=payload.credential_env_var;row.endpoint=payload.endpoint;row.updated_at=datetime.now(timezone.utc)
    else:
        row=CloudProviderConfig(provider=provider,enabled=payload.enabled,credential_env_var=payload.credential_env_var,endpoint=payload.endpoint);db.add(row)
    audit(db,"cloud_provider.configured","cloud_provider",provider,enabled=payload.enabled,credential_env_var=payload.credential_env_var);db.commit();return cloud_dict(row)

@app.get("/api/v1/security/status")
def security_status():
    return {"api_key_authentication":"enabled" if os.getenv("TOKENSCOPE_API_KEY") else "disabled_local_default","ingestion_rate_limit_per_minute":rate_limiter.limit,"maximum_body_bytes":5_000_000,"content_collection":False,"structured_access_logs":True,"security_headers":True,"warning":"Enable TOKENSCOPE_API_KEY before exposing TokenScope beyond localhost."}

@app.get("/api/v1/settings/retention")
def get_retention(db: Session = Depends(db_session)):
    row=db.get(AppSetting,"retention");return row.value if row else {"days":None,"automatic_deletion":False,"notice":"No telemetry is deleted automatically unless configured."}

@app.put("/api/v1/settings/retention")
def set_retention(payload: RetentionRequest, db: Session = Depends(db_session)):
    value={"days":payload.days,"automatic_deletion":False,"notice":"Use the explicit apply endpoint to delete records outside this window."};row=db.get(AppSetting,"retention")
    if row: row.value=value
    else: db.add(AppSetting(key="retention",value=value))
    audit(db,"retention.configured","setting","retention",days=payload.days);db.commit();return value

@app.post("/api/v1/settings/retention/apply")
def apply_retention(db: Session = Depends(db_session)):
    row=db.get(AppSetting,"retention")
    if not row or not row.value.get("days"): raise HTTPException(400,"A finite retention period must be configured first")
    cutoff=datetime.now(timezone.utc)-timedelta(days=row.value["days"]);result=db.execute(delete(TelemetryEvent).where(TelemetryEvent.timestamp<cutoff));audit(db,"retention.applied","telemetry",details_count=result.rowcount,cutoff=cutoff.date().isoformat());db.commit();return {"deleted":result.rowcount,"cutoff":cutoff}

@app.get("/api/v1/audit")
def audit_log(limit: int=Query(100,ge=1,le=1000),db: Session=Depends(db_session)):
    rows=db.execute(select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit)).scalars().all();return [{"audit_id":x.audit_id,"timestamp":x.timestamp,"action":x.action,"target_type":x.target_type,"target_id":x.target_id,"outcome":x.outcome,"details":x.details} for x in rows]

@app.get("/api/v1/export/configuration")
def export_configuration(db: Session = Depends(db_session)):
    return {"exported_at":datetime.now(timezone.utc),"retention":get_retention(db),"pricing_overrides":[{"model_id":x.model_id,"provider":x.provider,"input_price_per_million":x.input_price_per_million,"output_price_per_million":x.output_price_per_million,"cached_input_price_per_million":x.cached_input_price_per_million,"currency":x.currency} for x in db.execute(select(PriceOverride)).scalars().all()],"budgets":[{"name":x.name,"scope_type":x.scope_type,"scope_value":x.scope_value,"period":x.period,"amount":x.amount,"currency":x.currency} for x in db.execute(select(Budget)).scalars().all()],"cloud_providers":[cloud_dict(x) for x in db.execute(select(CloudProviderConfig)).scalars().all()],"secrets_included":False}

def csv_safe(value):
    text="" if value is None else str(value)
    return "'"+text if text.startswith(("=","+","-","@")) else text

@app.get("/api/v1/export/events.csv")
def export_events(limit: int=Query(100000,ge=1,le=100000),db: Session=Depends(db_session)):
    rows=db.execute(select(TelemetryEvent).order_by(TelemetryEvent.timestamp.desc()).limit(limit)).scalars().all();buffer=io.StringIO();fields=["event_id","timestamp","department","team","application","workload","provider","model","input_tokens","output_tokens","cached_input_tokens","total_tokens","latency_ms","success","estimated_total_cost","source"]
    writer=csv.DictWriter(buffer,fieldnames=fields);writer.writeheader()
    for row in rows: writer.writerow({key:csv_safe(getattr(row,key)) for key in fields})
    return Response(buffer.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=tokenscope-events.csv"})

def live_snapshot(db):
    since=datetime.now(timezone.utc)-timedelta(minutes=1)
    row=db.execute(select(func.count(),func.coalesce(func.sum(TelemetryEvent.total_tokens),0),func.coalesce(func.sum(TelemetryEvent.estimated_total_cost),0),func.sum(case((TelemetryEvent.success==False,1),else_=0)),func.count(func.distinct(TelemetryEvent.application))).where(TelemetryEvent.timestamp>=since)).one()
    return {"timestamp":datetime.now(timezone.utc).isoformat(),"requests_per_minute":row[0],"tokens_per_minute":row[1],"estimated_cost_per_hour":round(float(row[2] or 0)*60,4),"recent_errors":row[3] or 0,"active_applications":row[4] or 0,"label":"LIVE LOCAL WINDOW"}

@app.get("/api/v1/live/snapshot")
def get_live_snapshot(db: Session=Depends(db_session)):
    return live_snapshot(db)

@app.get("/api/v1/live/stream")
async def live_stream():
    async def events():
        while True:
            db=SessionLocal()
            try: payload=live_snapshot(db)
            finally: db.close()
            yield f"event: metrics\ndata: {json.dumps(payload)}\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/api/v1/efficiency")
def efficiency(days:int=Query(30,ge=1,le=365),db:Session=Depends(db_session)):
    clauses=filters_for(days)
    row=db.execute(select(func.count(),func.coalesce(func.sum(TelemetryEvent.estimated_total_cost),0),func.coalesce(func.sum(TelemetryEvent.cached_input_tokens),0),func.coalesce(func.sum(TelemetryEvent.input_tokens),0),func.coalesce(func.sum(TelemetryEvent.retry_count),0),func.sum(case((TelemetryEvent.success==False,1),else_=0)),func.coalesce(func.avg(func.coalesce(TelemetryEvent.context_utilization,0)),0)).where(*clauses)).one()
    return {"period_days":days,**efficiency_score(requests=row[0],spend=float(row[1]),cached_tokens=row[2],input_tokens=row[3],retries=row[4],failures=row[5] or 0,context_utilization=float(row[6]))}

@app.get("/api/v1/search")
def global_search(q:str=Query(min_length=2,max_length=100),limit:int=Query(20,ge=1,le=50),db:Session=Depends(db_session)):
    results=[]
    for kind,column in FILTER_FIELDS.items():
        for value in db.scalars(select(column).distinct().where(column.is_not(None),column.contains(q)).limit(limit)).all(): results.append({"type":kind,"label":value,"target":f"usage?{kind}={value}"})
    for budget in db.execute(select(Budget).where(Budget.name.contains(q)).limit(limit)).scalars().all(): results.append({"type":"budget","label":budget.name,"target":"budgets"})
    return {"query":q,"results":results[:limit]}

@app.get("/api/v1/settings/privacy")
def get_privacy(db:Session=Depends(db_session)):
    row=db.get(AppSetting,"privacy");value=row.value if row else PrivacyRequest().model_dump()
    return {**value,"notice":"TokenScope does not need prompt or response content to calculate usage, cost, forecasts, or most recommendations.","content_warning":bool(value.get("collect_prompt") or value.get("collect_response"))}

@app.put("/api/v1/settings/privacy")
def set_privacy(payload:PrivacyRequest,db:Session=Depends(db_session)):
    value=payload.model_dump();row=db.get(AppSetting,"privacy")
    if row: row.value=value
    else: db.add(AppSetting(key="privacy",value=value))
    audit(db,"privacy.configured","setting","privacy",content_enabled=value["collect_prompt"] or value["collect_response"],identity_enabled=value["collect_user_identity"]);db.commit()
    return get_privacy(db)

@app.get("/api/v1/reports/executive")
def executive_report(days:int=Query(30,ge=7,le=365),db:Session=Depends(db_session)):
    overview_data=overview(days,db);optimization_data=optimization(days,db);anomaly_data=anomalies(max(14,days),10,db);budget_data=list_budgets(db)
    latest=db.execute(select(ForecastRun).order_by(ForecastRun.created_at.desc())).scalars().first()
    return {"title":"TokenScope Executive AI Usage Report","generated_at":datetime.now(timezone.utc),"period_days":days,"labels":{"usage":"OBSERVED","spend":"ESTIMATED","forecast":"FORECASTED","savings":"ESTIMATED"},"usage":overview_data["totals"],"largest_applications":overview_data["applications"][:5],"largest_models":overview_data["models"][:5],"optimization":optimization_data["summary"],"top_opportunities":optimization_data["recommendations"][:5],"anomalies":{"count":len(anomaly_data["anomalies"]),"items":anomaly_data["anomalies"][:5]},"budgets":budget_data["budgets"],"latest_forecast":None if not latest else {"metric":latest.metric,"horizon_days":latest.horizon_days,"model":latest.selected_model,"smape":latest.error_value,"created_at":latest.created_at},"privacy":"Metadata-only analytics; prompt and response content are not required."}

@app.get("/api/v1/reports/executive.csv")
def executive_report_csv(days:int=Query(30,ge=7,le=365),db:Session=Depends(db_session)):
    report=executive_report(days,db);buffer=io.StringIO();writer=csv.writer(buffer);writer.writerow(["section","metric","value","label"])
    for key,value in report["usage"].items(): writer.writerow(["usage",key,csv_safe(value),"OBSERVED" if key!="spend" else "ESTIMATED"])
    writer.writerow(["optimization","potential_monthly_savings",report["optimization"]["estimated_monthly_savings"],"ESTIMATED"])
    writer.writerow(["anomalies","count",report["anomalies"]["count"],"OBSERVED"])
    return Response(buffer.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=tokenscope-executive-report.csv"})

def evaluation_summary(db,model):
    rows=db.execute(select(ModelEvaluation.metric,func.avg(ModelEvaluation.score/ModelEvaluation.maximum_score*100),func.sum(func.coalesce(ModelEvaluation.sample_size,1)),func.count()).where(ModelEvaluation.model==model).group_by(ModelEvaluation.metric)).all()
    return [{"metric":r[0],"normalized_score_percent":round(float(r[1]),2),"total_samples":r[2],"evaluation_runs":r[3],"source":"USER-SUPPLIED EVALUATIONS"} for r in rows]

def model_stats(db,model,days):
    since=datetime.now(timezone.utc)-timedelta(days=days)
    row=db.execute(select(func.count(),func.sum(case((TelemetryEvent.success==True,1),else_=0)),func.coalesce(func.avg(TelemetryEvent.latency_ms),0),func.coalesce(func.avg(case((TelemetryEvent.latency_ms>0,TelemetryEvent.output_tokens/(TelemetryEvent.latency_ms/1000.0)),else_=None)),0),func.coalesce(func.sum(TelemetryEvent.estimated_total_cost),0),func.coalesce(func.avg(TelemetryEvent.input_tokens),0),func.coalesce(func.avg(func.coalesce(TelemetryEvent.context_utilization,0)),0),func.coalesce(func.sum(TelemetryEvent.total_tokens),0)).where(TelemetryEvent.timestamp>=since,TelemetryEvent.model==model)).one()
    identity=db.execute(select(TelemetryEvent.provider,TelemetryEvent.deployment_type,func.count()).where(TelemetryEvent.timestamp>=since,TelemetryEvent.model==model).group_by(TelemetryEvent.provider,TelemetryEvent.deployment_type).order_by(func.count().desc())).first()
    price=get_price(model,db);requests=row[0] or 0
    return {"model":model,"provider":identity[0] if identity else price.provider,"deployment":identity[1] if identity else "unknown","input_price_per_million":price.input,"output_price_per_million":price.output,"cached_input_price_per_million":price.cached,"requests":requests,"success_rate":round((row[1] or 0)/requests*100,2) if requests else None,"observed_latency_ms":round(float(row[2]),2) if requests else None,"observed_tokens_per_second":round(float(row[3]),2) if requests else None,"historical_cost":round(float(row[4]),4),"average_context_tokens":round(float(row[5]),1) if requests else None,"average_context_utilization":round(float(row[6]),4) if requests else None,"observed_total_tokens":row[7] or 0,"estimated_monthly_cost_at_observed_rate":round(float(row[4])*30/days,4),"quality_metrics":evaluation_summary(db,model)}

@app.get("/api/v1/models/inventory")
def model_inventory(days:int=Query(30,ge=1,le=365),db:Session=Depends(db_session)):
    observed=[row[0] for row in db.execute(select(TelemetryEvent.model).distinct()).all()];known=[x["model_id"] for x in registry(db)];models=sorted(set(observed+known))
    return {"period_days":days,"models":[model_stats(db,model,days) for model in models],"quality_policy":"Quality metrics appear only when supplied through the evaluation API."}

@app.get("/api/v1/models/compare")
def compare_models(models:str,days:int=Query(30,ge=1,le=365),db:Session=Depends(db_session)):
    selected=list(dict.fromkeys(item.strip() for item in models.split(",") if item.strip()))
    if len(selected)<2 or len(selected)>5: raise HTTPException(422,"Select between 2 and 5 unique models")
    return {"period_days":days,"models":[model_stats(db,model,days) for model in selected],"disclaimer":"Cost comparison only unless user-supplied evaluation metrics are displayed. Output quality is not assumed equivalent.","labels":{"performance":"OBSERVED","price":"CONFIGURED","monthly_cost":"ESTIMATED","quality":"USER-SUPPLIED ONLY"}}

@app.post("/api/v1/evaluations",status_code=201)
def create_evaluation(payload:ModelEvaluationCreate,db:Session=Depends(db_session)):
    row=ModelEvaluation(**payload.model_dump());db.add(row);db.flush();audit(db,"model_evaluation.created","evaluation",row.evaluation_id,model=row.model,metric=row.metric,source=row.source);db.commit()
    return {"evaluation_id":row.evaluation_id,"normalized_score_percent":round(row.score/row.maximum_score*100,2),"quality_label":"USER-SUPPLIED EVALUATION"}

@app.get("/api/v1/evaluations")
def list_evaluations(model:str|None=None,application:str|None=None,limit:int=Query(100,ge=1,le=1000),db:Session=Depends(db_session)):
    clauses=[]
    if model: clauses.append(ModelEvaluation.model==model)
    if application: clauses.append(ModelEvaluation.application==application)
    rows=db.execute(select(ModelEvaluation).where(*clauses).order_by(ModelEvaluation.timestamp.desc()).limit(limit)).scalars().all()
    return [{"evaluation_id":x.evaluation_id,"timestamp":x.timestamp,"model":x.model,"application":x.application,"workload":x.workload,"metric":x.metric,"score":x.score,"maximum_score":x.maximum_score,"normalized_score_percent":round(x.score/x.maximum_score*100,2),"sample_size":x.sample_size,"source":x.source,"notes":x.notes,"quality_label":"USER-SUPPLIED"} for x in rows]

@app.delete("/api/v1/evaluations/{evaluation_id}")
def delete_evaluation(evaluation_id:str,db:Session=Depends(db_session)):
    row=db.get(ModelEvaluation,evaluation_id)
    if not row: raise HTTPException(404,"Evaluation not found")
    audit(db,"model_evaluation.deleted","evaluation",evaluation_id,model=row.model);db.delete(row);db.commit();return {"deleted":evaluation_id}


# ==================== LARGE-FILE IMPORT ENDPOINTS ====================

@app.post("/api/v1/import/start", status_code=201)
def start_import(payload: FileUploadStart, db: Session = Depends(db_session)):
    """Initiate a large file import. Returns import_id for subsequent operations."""
    from .importer_streaming import validate_file_metadata
    
    try:
        validate_file_metadata(payload.filename, payload.file_size, payload.format)
    except Exception as e:
        raise HTTPException(400, str(e))
    
    active = db.scalar(select(func.count()).select_from(ImportJob).where(ImportJob.status.in_(("UPLOADED", "ANALYZING", "READY", "IMPORTING")))) or 0
    if active >= 10:
        raise HTTPException(429, "Too many active imports; cancel or complete an existing import")

    # Create import job record
    import_id = str(uuid4())
    job = ImportJob(
        import_id=import_id,
        filename=payload.filename,
        file_size=payload.file_size,
        format=payload.format,
        status="UPLOADED"
    )
    db.add(job)
    audit(db, "import.started", "import", import_id, filename=payload.filename, file_size=payload.file_size, format=payload.format)
    db.commit()
    
    return {"import_id": import_id, "status": "UPLOADED", "max_file_size_mb": 500}


@app.post("/api/v1/import/{import_id}/upload")
async def upload_chunk(import_id: str, file: UploadFile = File(...), db: Session = Depends(db_session)):
    """Upload a file chunk for large import."""
    # Validate import exists
    job = db.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    if job.status not in ["UPLOADED", "ANALYZING"]:
        raise HTTPException(400, f"Cannot upload to import in {job.status} status")
    
    # Read and store chunk
    importer = StreamingImporter(import_id)
    try:
        uploaded = await importer.receive_upload(file, job.file_size)
    except Exception as e:
        raise HTTPException(400, "File upload was rejected") from e
    
    return {"uploaded": uploaded, "import_id": import_id}


@app.post("/api/v1/import/{import_id}/analyze")
async def analyze_import(import_id: str, db: Session = Depends(db_session)):
    """Analyze uploaded file: detect format, encoding, delimiter, row count."""
    job = db.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    if job.status != "UPLOADED":
        raise HTTPException(400, f"Cannot analyze import in {job.status} status")
    
    # Update status
    job.status = "ANALYZING"
    db.commit()
    
    try:
        importer = StreamingImporter(import_id)
        importer.verify_complete(job.file_size)
        analysis = await importer.analyze_file(job.filename, job.format)
        
        # Update job with analysis results
        job = db.get(ImportJob, import_id)
        if job:
            job.total_rows = analysis["total_rows"]
            job.detected_encoding = analysis["detected_encoding"]
            job.detected_delimiter = analysis["detected_delimiter"]
            job.sample_rows = analysis["sample_rows"]
            job.status = "READY"
            db.commit()
        
        # Generate auto-mapping
        auto_mapping = {}
        if job.format == "csv" and analysis["sample_rows"]:
            from .importer_streaming import auto_map_columns
            headers = list(analysis["sample_rows"][0].keys())
            auto_mapping = auto_map_columns(headers)
        
        return {
            "import_id": import_id,
            "status": "READY",
            "total_rows": analysis["total_rows"],
            "detected_encoding": analysis["detected_encoding"],
            "detected_delimiter": analysis["detected_delimiter"],
            "sample_rows": analysis["sample_rows"][:25],
            "auto_mapping": auto_mapping,
            "validation_summary": analysis["validation_summary"]
        }
    except Exception as e:
        job.status = "FAILED"
        job.failure_reason = str(e)[:500]
        db.commit()
        StreamingImporter(import_id).cleanup()
        raise HTTPException(400, "Analysis failed; verify the file format and content") from e


@app.get("/api/v1/import/{import_id}/status")
def get_import_status(import_id: str, db: Session = Depends(db_session)):
    """Get current status and progress of an import."""
    job = db.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    
    progress_percent = 0
    if job.total_rows > 0:
        progress_percent = min(100, int(job.processed_rows / job.total_rows * 100))
    
    rate = 0.0
    if job.processed_rows > 0 and job.started_at:
        elapsed = (datetime.now(timezone.utc) - ensure_aware(job.started_at)).total_seconds()
        if elapsed > 0:
            rate = job.processed_rows / elapsed
    
    return {
        "import_id": import_id,
        "filename": job.filename,
        "file_size": job.file_size,
        "format": job.format,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "valid_rows": job.valid_rows,
        "rejected_rows": job.rejected_rows,
        "inserted_rows": job.inserted_rows,
        "duplicate_skipped": job.duplicate_skipped,
        "error_count": job.error_count,
        "cancelled": job.cancelled,
        "failure_reason": job.failure_reason,
        "progress_percent": progress_percent,
        "rate_rows_per_sec": round(rate, 2)
    }


@app.post("/api/v1/import/{import_id}/commit")
async def commit_import(import_id: str, payload: ImportCommit, db: Session = Depends(db_session)):
    """Start the actual import process."""
    job = db.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    if job.status != "READY":
        raise HTTPException(400, f"Cannot start import in {job.status} status")
    if not payload.mapping:
        job.status = "FAILED"
        job.failure_reason = "Column mapping is required before committing an import"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        StreamingImporter(import_id).cleanup()
        raise HTTPException(400, "Column mapping is required before committing an import")
    
    # Update status
    job.status = "IMPORTING"
    job.started_at = datetime.now(timezone.utc)
    job.mapping = payload.mapping
    db.commit()
    
    try:
        importer = StreamingImporter(import_id)
        results = await importer.execute_import(
            mapping=payload.mapping,
            duplicate_handling=payload.duplicate_handling,
            chunk_size=1000
        )
        
        return {
            "import_id": import_id,
            "status": "COMPLETED",
            "processed_rows": results["processed_rows"],
            "valid_rows": results["valid_rows"],
            "rejected_rows": results["rejected_rows"],
            "inserted_rows": results["inserted_rows"],
            "duplicate_skipped": results["duplicate_skipped"]
        }
    except Exception as e:
        db.rollback()
        job = db.get(ImportJob, import_id)
        if job:
            job.status = "FAILED"
            job.failure_reason = str(e)[:500]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        StreamingImporter(import_id).cleanup()
        raise HTTPException(400, "Import failed; verify column mapping and source data") from e


@app.delete("/api/v1/import/{import_id}/cancel")
def cancel_import(import_id: str, db: Session = Depends(db_session)):
    """Cancel an in-progress or pending import."""
    job = db.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    if job.status not in ["UPLOADED", "ANALYZING", "READY", "IMPORTING"]:
        raise HTTPException(400, f"Cannot cancel import in {job.status} status")
    
    importer = StreamingImporter(import_id)
    importer.cancel()
    
    audit(db, "import.cancelled", "import", import_id)
    db.commit()
    return {"import_id": import_id, "status": "CANCELLED"}


@app.get("/api/v1/import/{import_id}/rejected")
def get_rejected_rows(import_id: str, include_values: bool = Query(False), db: Session = Depends(db_session)):
    """Export rejected rows as CSV."""
    job = db.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    if not job.rejected_row_examples:
        return Response("", media_type="text/csv")
    
    csv_content = export_rejected_rows_csv(import_id, include_values)
    filename = f"rejected-rows-{import_id[:8]}.csv"
    return Response(csv_content, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.get("/api/v1/import/history")
def import_history(limit: int = Query(50, ge=1, le=500), db: Session = Depends(db_session)):
    """List past import jobs."""
    jobs = db.execute(
        select(ImportJob).order_by(ImportJob.created_at.desc()).limit(limit)
    ).scalars().all()
    
    items = []
    for job in jobs:
        duration = None
        if job.completed_at and job.started_at:
            duration = int((ensure_aware(job.completed_at) - ensure_aware(job.started_at)).total_seconds())
        elif job.started_at:
            duration = int((datetime.now(timezone.utc) - ensure_aware(job.started_at)).total_seconds())
        
        items.append({
            "import_id": job.import_id,
            "filename": job.filename,
            "file_size": job.file_size,
            "format": job.format,
            "status": job.status,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "duration_seconds": duration,
            "total_rows": job.total_rows,
            "inserted_rows": job.inserted_rows,
            "rejected_rows": job.rejected_rows,
            "error_count": job.error_count
        })
    
    return {"imports": items, "count": len(items)}


@app.delete("/api/v1/import/{import_id}")
def delete_import_batch(import_id: str, db: Session = Depends(db_session)):
    """Delete all telemetry events from a specific import."""
    job = db.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    if job.status not in ["COMPLETED", "FAILED", "CANCELLED"]:
        raise HTTPException(400, f"Can only delete completed, failed, or cancelled imports")
    
    # Delete all events from this import (marked by source="import" and timestamp matching job window)
    deleted = db.execute(
        delete(TelemetryEvent).where(
            TelemetryEvent.source == "import",
            TelemetryEvent.timestamp >= job.created_at,
            TelemetryEvent.timestamp <= (job.completed_at or datetime.now(timezone.utc))
        )
    )
    audit(db, "import.batch_deleted", "import", import_id, rows_deleted=deleted.rowcount)
    db.commit()
    return {"import_id": import_id, "deleted_rows": deleted.rowcount}
