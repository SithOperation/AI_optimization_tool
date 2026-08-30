from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, AutoETS, MSTL, Naive, SeasonalNaive, Theta

METRICS = {"requests", "input_tokens", "output_tokens", "total_tokens", "spend"}

class InsufficientHistory(ValueError): pass

def smape(actual, predicted) -> float:
    actual=np.asarray(actual,dtype=float);predicted=np.asarray(predicted,dtype=float)
    denominator=np.abs(actual)+np.abs(predicted)
    return float(np.mean(np.where(denominator==0,0,2*np.abs(predicted-actual)/denominator))*100)

def candidates(points: int):
    models=[Naive(alias="Naive"),SeasonalNaive(season_length=7,alias="SeasonalNaive"),AutoETS(season_length=7,alias="AutoETS"),AutoARIMA(season_length=7,alias="AutoARIMA"),Theta(season_length=7,alias="Theta")]
    if points>=56: models.append(MSTL(season_length=[7],trend_forecaster=AutoETS(season_length=7),alias="MSTL"))
    return models

def _frame(dates, values): return pd.DataFrame({"unique_id":"organization","ds":pd.to_datetime(dates),"y":np.asarray(values,dtype=float)})

def run_forecast(dates, values, horizon: int):
    points=len(values)
    if points<21: raise InsufficientHistory(f"More historical data is needed for a reliable forecast. Found {points} daily observations; at least 21 are required.")
    if horizon==365 and points<120: raise InsufficientHistory(f"A 12-month forecast requires at least 120 daily observations. Found {points}.")
    if horizon>points*3: raise InsufficientHistory(f"A {horizon}-day horizon is too long for {points} observations. Add more history or choose a shorter horizon.")
    holdout=min(14,max(7,points//4)); train=_frame(dates[:-holdout],values[:-holdout]); actual=values[-holdout:]
    scores=[]
    for model in candidates(points):
        name=model.alias
        try:
            predicted=StatsForecast(models=[model],freq="D",n_jobs=1).forecast(df=train,h=holdout)[name].to_numpy()
            scores.append({"model":name,"smape":round(smape(actual,predicted),3),"status":"completed"})
        except Exception as error:
            scores.append({"model":name,"smape":None,"status":"failed","reason":type(error).__name__})
    valid=[item for item in scores if item["smape"] is not None]
    if not valid: raise RuntimeError("All statistical forecast candidates failed during backtesting")
    winner=min(valid,key=lambda item:item["smape"]); selected=next(model for model in candidates(points) if model.alias==winner["model"])
    result=StatsForecast(models=[selected],freq="D",n_jobs=1).forecast(df=_frame(dates,values),h=horizon,level=[95])
    name=winner["model"]; expected=result[name].to_numpy(); lower=result[f"{name}-lo-95"].to_numpy(); upper=result[f"{name}-hi-95"].to_numpy()
    last=pd.Timestamp(dates[-1]); future=[(last+timedelta(days=i+1)).date().isoformat() for i in range(horizon)]
    return {"selected_model":name,"error_value":winner["smape"],"backtests":sorted(scores,key=lambda x:x["smape"] if x["smape"] is not None else 1e9),"values":[{"date":date,"expected":max(0,float(e)),"lower":max(0,float(lo)),"upper":max(0,float(hi))} for date,e,lo,hi in zip(future,expected,lower,upper)]}

def explain_drivers(daily, applications):
    values=[row["value"] for row in daily];half=max(7,len(values)//2)
    recent=np.mean(values[-half:]); previous=np.mean(values[-half*2:-half]) if len(values)>=half*2 else np.mean(values[:half])
    change=((recent/previous)-1)*100 if previous else 0
    drivers=[{"label":"Historical trend","evidence":f"Daily usage changed {change:+.1f}% between the comparison periods.","kind":"observed"}]
    if applications:
        top=applications[0];total=sum(x["value"] for x in applications) or 1
        drivers.append({"label":top["name"],"evidence":f"This application accounts for {top['value']/total*100:.1f}% of the observed metric.","kind":"observed"})
    drivers.append({"label":"Model selection","evidence":"Candidate models were compared on held-out historical observations using sMAPE.","kind":"estimated"})
    return drivers
