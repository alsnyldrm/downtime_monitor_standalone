from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app import templates
from app.dependencies import get_current_user, require_login
from app.database import SessionLocal
from app.models.monitor import Monitor, MonitorStatus
from app.models.monitor_log import MonitorLog, LogStatus
from app.models.incident import Incident
from app.models.user import User
from sqlalchemy import func
from datetime import datetime, timezone, timedelta

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = require_login(request)
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        day_ago = now - timedelta(hours=24)

        monitors = db.query(Monitor).filter(Monitor.is_active == True).all()
        total = len(monitors)
        up_count = sum(1 for m in monitors if m.status == MonitorStatus.up)
        down_count = sum(1 for m in monitors if m.status == MonitorStatus.down)
        paused_count = sum(1 for m in monitors if m.status == MonitorStatus.paused)
        pending_count = sum(1 for m in monitors if m.status == MonitorStatus.pending)

        # Avg response time (last 24h, only UP checks)
        avg_rt = db.query(func.avg(MonitorLog.response_time)).filter(
            MonitorLog.checked_at >= day_ago, MonitorLog.status == LogStatus.up
        ).scalar()

        # Active incidents (no end time)
        active_incidents_count = db.query(Incident).filter(Incident.ended_at == None).count()

        # Checks in last 24h
        checks_24h = db.query(func.count(MonitorLog.id)).filter(MonitorLog.checked_at >= day_ago).scalar() or 0
        failures_24h = db.query(func.count(MonitorLog.id)).filter(
            MonitorLog.checked_at >= day_ago, MonitorLog.status == LogStatus.down
        ).scalar() or 0

        # Overall uptime % across all monitors (last 24h)
        success_rate_24h = ((checks_24h - failures_24h) / checks_24h * 100) if checks_24h > 0 else None

        recent_incidents = db.query(Incident).order_by(Incident.started_at.desc()).limit(10).all()

        monitor_data = []
        for m in monitors:
            last_logs = db.query(MonitorLog).filter(MonitorLog.monitor_id == m.id).order_by(MonitorLog.checked_at.desc()).limit(50).all()
            monitor_data.append({"monitor": m, "logs": list(reversed(last_logs))})

        return templates.TemplateResponse("dashboard/index.html", {
            "request": request,
            "user": user,
            "monitors": monitor_data,
            "total": total,
            "up_count": up_count,
            "down_count": down_count,
            "paused_count": paused_count,
            "pending_count": pending_count,
            "recent_incidents": recent_incidents,
            "avg_rt": avg_rt,
            "active_incidents_count": active_incidents_count,
            "checks_24h": checks_24h,
            "failures_24h": failures_24h,
            "success_rate_24h": success_rate_24h,
        })
    finally:
        db.close()


@router.post("/api/preferences/theme")
async def set_theme(request: Request):
    user = require_login(request)
    body = await request.json()
    theme = body.get("theme", "dark")
    if theme not in ("dark", "light"):
        theme = "dark"
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user.id).update({"theme": theme})
        db.commit()
    finally:
        db.close()
    return JSONResponse({"ok": True})


@router.post("/api/preferences/sidebar")
async def set_sidebar(request: Request):
    user = require_login(request)
    body = await request.json()
    pinned = bool(body.get("pinned", True))
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user.id).update({"sidebar_pinned": pinned})
        db.commit()
    finally:
        db.close()
    return JSONResponse({"ok": True})


@router.get("/api/status", response_class=HTMLResponse)
async def api_status(request: Request):
    from fastapi.responses import JSONResponse
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    db = SessionLocal()
    try:
        monitors = db.query(Monitor).filter(Monitor.is_active == True).all()
        data = []
        for m in monitors:
            data.append({
                "id": m.id,
                "name": m.name,
                "status": m.status.value if m.status else "pending",
                "uptime": m.uptime_percentage or 0,
                "response_time": m.last_response_time or 0,
                "last_checked": m.last_checked_at.isoformat() if m.last_checked_at else None,
            })
        up = sum(1 for d in data if d["status"] == "up")
        down = sum(1 for d in data if d["status"] == "down")
        return JSONResponse({"monitors": data, "up": up, "down": down, "total": len(data)})
    finally:
        db.close()
