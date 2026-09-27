import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Arrival, BunchReport, Line, Trip
from app.services.bunch_engine import detect_bunching, events_to_dicts
router = APIRouter(prefix="/reports", tags=["reports"])

def _collect_arrivals(db: Session, line_id: int, stop_name: str | None) -> tuple[Line, list[dict]]:
    """加载线路当前阈值与到站数据；只读，不产生任何写入。"""
    line = db.get(Line, line_id)
    if not line:
        raise HTTPException(404, "线路不存在")
    trips = db.scalars(select(Trip).where(Trip.line_id == line_id)).all()
    trip_ids = [t.id for t in trips]
    trip_no_map = {t.id: t.trip_no for t in trips}
    arrivals = db.scalars(select(Arrival).where(Arrival.trip_id.in_(trip_ids))).all()
    payload = [{"stop_name": a.stop_name, "trip_no": trip_no_map[a.trip_id], "actual_arrive": a.actual_arrive}
               for a in arrivals if stop_name is None or a.stop_name == stop_name]
    return line, payload

def _compute_events(line: Line, payload: list[dict]) -> list[dict]:
    """用线路当前阈值跑检测，返回普通 dict 列表（不持久化）。"""
    events = detect_bunching(payload, line.planned_headway_min, line.bunch_threshold, line.large_threshold)
    return events_to_dicts(events)

def _serialize_report(r: BunchReport) -> dict:
    return {"id": r.id, "line_id": r.line_id, "stop_name": r.stop_name,
            "created_at": r.created_at.isoformat(), "events": json.loads(r.summary_json)}

@router.get("")
def list_reports(db: Session = Depends(get_db)):
    rows = db.scalars(select(BunchReport).order_by(BunchReport.id.desc())).all()
    return [_serialize_report(r) for r in rows]

@router.post("/preview")
def preview_detection(line_id: int, stop_name: str | None = None, db: Session = Depends(get_db)):
    """试算：用当前阈值跑完全线或指定站，返回事件列表，但不写入任何报告记录。"""
    line, payload = _collect_arrivals(db, line_id, stop_name)
    data = _compute_events(line, payload)
    return {"line_id": line_id, "stop_name": stop_name or "*", "saved": False, "events": data}

@router.post("/run")
def run_detection(line_id: int, stop_name: str | None = None, db: Session = Depends(get_db)):
    line, payload = _collect_arrivals(db, line_id, stop_name)
    data = _compute_events(line, payload)
    report = BunchReport(line_id=line_id, stop_name=stop_name or "*", created_at=datetime.utcnow(),
                         summary_json=json.dumps(data, ensure_ascii=False))
    db.add(report); db.commit(); db.refresh(report)
    return {"id": report.id, "line_id": line_id, "stop_name": report.stop_name, "saved": True, "events": data}

@router.get("/suggestions")
def suggestions(line_id: int, db: Session = Depends(get_db)):
    # 建议页只读：复用试算逻辑，不再借道 run_detection 产生报告写入
    line, payload = _collect_arrivals(db, line_id, None)
    data = _compute_events(line, payload)
    return {"line_id": line_id, "suggestions": [e for e in data if e["status"] != "normal"]}

@router.get("/timeline")
def timeline(line_id: int, stop_name: str = "市民中心", db: Session = Depends(get_db)):
    trips = db.scalars(select(Trip).where(Trip.line_id == line_id)).all()
    trip_ids = [t.id for t in trips]
    trip_no_map = {t.id: t.trip_no for t in trips}
    arrivals = sorted(db.scalars(select(Arrival).where(Arrival.trip_id.in_(trip_ids), Arrival.stop_name == stop_name)).all(),
                      key=lambda a: a.actual_arrive)
    if not arrivals: return {"stop_name": stop_name, "marks": []}
    t0 = arrivals[0].actual_arrive
    span = max((arrivals[-1].actual_arrive - t0).total_seconds(), 1)
    marks = [{"trip_no": trip_no_map[a.trip_id], "actual_arrive": a.actual_arrive.isoformat(),
              "pct": round((a.actual_arrive - t0).total_seconds() / span * 100, 2)} for a in arrivals]
    return {"stop_name": stop_name, "marks": marks}
