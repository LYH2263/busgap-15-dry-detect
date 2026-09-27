import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import BunchReport
from app.services.seed import seed_if_empty


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestSession()
    seed_if_empty(db)  # 写入 B12 线路及其班次/到站
    db.close()

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # 不进入 with 上下文：避免 lifespan 触发 Base.metadata.create_all 连接默认 Postgres。
    # 所有请求都经依赖覆盖走内存 sqlite。
    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def b12_id(client) -> int:
    rows = client.get("/api/lines").json()
    return next(r["id"] for r in rows if r["code"] == "B12")


def report_count(SessionLocal) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(func.count()).select_from(BunchReport)) or 0
    finally:
        db.close()


def test_preview_b12_keeps_report_count_unchanged(client):
    c, SessionLocal = client
    line_id = b12_id(c)
    before = report_count(SessionLocal)

    resp = c.post(f"/api/reports/preview?line_id={line_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["saved"] is False
    assert "id" not in body  # 试算不产生报告记录，因此没有报告 id
    assert body["line_id"] == line_id
    assert body["stop_name"] == "*"
    assert len(body["events"]) > 0  # B12 seed 中存在串车/大间隔事件

    # 再跑一次试算，历史报告条数仍与试算前相同
    c.post(f"/api/reports/preview?line_id={line_id}")
    assert report_count(SessionLocal) == before


def test_preview_specific_stop_keeps_report_count_unchanged(client):
    c, SessionLocal = client
    line_id = b12_id(c)
    before = report_count(SessionLocal)

    resp = c.post(f"/api/reports/preview?line_id={line_id}&stop_name=市民中心")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stop_name"] == "市民中心"
    assert body["saved"] is False
    assert all(e["stop_name"] == "市民中心" for e in body["events"])

    assert report_count(SessionLocal) == before


def test_run_detection_still_creates_one_report(client):
    c, SessionLocal = client
    line_id = b12_id(c)
    before = report_count(SessionLocal)

    resp = c.post(f"/api/reports/run?line_id={line_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["saved"] is True
    assert body["id"] is not None

    assert report_count(SessionLocal) == before + 1
    saved = c.get("/api/reports").json()
    assert any(r["id"] == body["id"] for r in saved)


def test_preview_after_run_does_not_change_count(client):
    c, SessionLocal = client
    line_id = b12_id(c)
    c.post(f"/api/reports/run?line_id={line_id}")
    before_run = report_count(SessionLocal)
    assert before_run == 1

    resp = c.post(f"/api/reports/preview?line_id={line_id}")
    assert resp.status_code == 200
    assert resp.json()["saved"] is False
    assert report_count(SessionLocal) == before_run


def test_suggestions_is_read_only(client):
    c, SessionLocal = client
    line_id = b12_id(c)
    before = report_count(SessionLocal)

    resp = c.get(f"/api/reports/suggestions?line_id={line_id}")
    assert resp.status_code == 200
    assert all(e["status"] != "normal" for e in resp.json()["suggestions"])
    assert report_count(SessionLocal) == before


def test_preview_unknown_line_404(client):
    c, _SessionLocal = client
    resp = c.post("/api/reports/preview?line_id=9999")
    assert resp.status_code == 404
