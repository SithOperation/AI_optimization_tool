from __future__ import annotations

import math
from statistics import mean, pstdev

def detect(series_by_group: dict[str,list[dict]], limit: int = 30) -> list[dict]:
    findings=[]
    for group,points in series_by_group.items():
        values=[float(point["value"]) for point in points]
        for index in range(7,len(values)):
            baseline=values[max(0,index-28):index]
            avg=mean(baseline); deviation=pstdev(baseline)
            value=values[index]; ratio=value/avg if avg else 0
            z=(value-avg)/deviation if deviation else (3 if value>avg*1.5 else 0)
            if z<2.5 or ratio<1.35: continue
            severity="CRITICAL" if z>=5 or ratio>=3 else "HIGH" if z>=4 or ratio>=2 else "MEDIUM"
            findings.append({"id":f"{group}-{points[index]['date']}","severity":severity,"category":"TOKEN_SPIKE","entity":group,"timestamp":points[index]["date"],"observed":round(value,2),"baseline":round(avg,2),"ratio":round(ratio,2),"z_score":round(z,2),"explanation":f"{group} token usage was {ratio:.1f}x its trailing baseline.","evidence":f"Observed {value:,.0f} tokens versus a {avg:,.0f} token daily baseline."})
    rank={"CRITICAL":4,"HIGH":3,"MEDIUM":2,"LOW":1,"INFO":0}
    return sorted(findings,key=lambda x:(rank[x["severity"]],x["timestamp"]),reverse=True)[:limit]
