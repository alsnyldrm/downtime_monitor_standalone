from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.database import get_db, SessionLocal
from app.dependencies import require_login, require_editor, require_admin, get_current_user
from app.models.monitor import Monitor, MonitorType, MonitorStatus
from app.models.monitor_log import MonitorLog
from app.models.incident import Incident
from app.models.monitor_group import MonitorGroup

router = APIRouter(prefix="/monitors")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def monitor_list(request: Request):
    user = require_login(request)
    db = SessionLocal()
    try:
        monitors = db.query(Monitor).order_by(Monitor.created_at.desc()).all()
        return templates.TemplateResponse("monitors/list.html", {"request": request, "user": user, "monitors": monitors})
    finally:
        db.close()


@router.get("/new", response_class=HTMLResponse)
async def monitor_new(request: Request):
    user = require_editor(request)
    db = SessionLocal()
    try:
        groups = db.query(MonitorGroup).order_by(MonitorGroup.name).all()
        return templates.TemplateResponse("monitors/form.html", {"request": request, "user": user, "monitor": None, "monitor_types": [t.value for t in MonitorType], "groups": groups})
    finally:
        db.close()


@router.post("/new")
async def monitor_create(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    url: str = Form(...),
    port: str = Form(None),
    keyword: str = Form(None),
    group_id: str = Form(None),
    interval: int = Form(300),
    timeout: int = Form(30),
    http_method: str = Form("GET"),
    follow_redirects: str = Form(None),
    notification_email: str = Form(None),
    db: Session = Depends(get_db),
):
    user = require_editor(request)
    port_val = int(port) if port and port.strip() else None
    group_val = int(group_id) if group_id and group_id.strip() else None
    monitor = Monitor(
        name=name,
        type=MonitorType(type),
        url=url,
        port=port_val,
        group_id=group_val,
        keyword=keyword if keyword and keyword.strip() else None,
        interval=max(5, interval),
        timeout=min(timeout, 120),
        http_method=http_method or "GET",
        follow_redirects=(follow_redirects == "on"),
        is_active=True,
        status=MonitorStatus.pending,
        notification_email=notification_email if notification_email and notification_email.strip() else None,
        created_by=user.id,
    )
    db.add(monitor)
    db.commit()
    return RedirectResponse(url="/monitors", status_code=303)


@router.get("/{monitor_id}", response_class=HTMLResponse)
async def monitor_detail(request: Request, monitor_id: int):
    from datetime import timedelta
    from sqlalchemy import func
    user = require_login(request)
    db = SessionLocal()
    try:
        monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        if not monitor:
            return RedirectResponse(url="/monitors", status_code=303)
        logs = db.query(MonitorLog).filter(MonitorLog.monitor_id == monitor_id).order_by(MonitorLog.checked_at.desc()).limit(100).all()
        incidents = db.query(Incident).filter(Incident.monitor_id == monitor_id).order_by(Incident.started_at.desc()).limit(50).all()
        now = datetime.now(timezone.utc)
        # Son 24 saat istatistikleri
        since_24h = now - timedelta(hours=24)
        since_7d = now - timedelta(days=7)
        since_30d = now - timedelta(days=30)
        logs_24h = db.query(MonitorLog).filter(MonitorLog.monitor_id == monitor_id, MonitorLog.checked_at >= since_24h).all()
        logs_7d = db.query(MonitorLog).filter(MonitorLog.monitor_id == monitor_id, MonitorLog.checked_at >= since_7d).all()
        logs_30d = db.query(MonitorLog).filter(MonitorLog.monitor_id == monitor_id, MonitorLog.checked_at >= since_30d).all()
        def calc_uptime(log_list):
            if not log_list: return None
            up = sum(1 for l in log_list if l.status.value == 'up')
            return round(up / len(log_list) * 100, 2)
        def calc_rt(log_list):
            rts = [l.response_time for l in log_list if l.response_time is not None]
            if not rts: return None, None, None
            return round(sum(rts)/len(rts),1), round(min(rts),1), round(max(rts),1)
        uptime_24h = calc_uptime(logs_24h)
        uptime_7d = calc_uptime(logs_7d)
        uptime_30d = calc_uptime(logs_30d)
        rt_avg, rt_min, rt_max = calc_rt(logs_24h)
        return templates.TemplateResponse("monitors/detail.html", {
            "request": request, "user": user, "monitor": monitor, "logs": logs, "incidents": incidents,
            "uptime_24h": uptime_24h, "uptime_7d": uptime_7d, "uptime_30d": uptime_30d,
            "rt_avg": rt_avg, "rt_min": rt_min, "rt_max": rt_max,
        })
    finally:
        db.close()


@router.get("/{monitor_id}/edit", response_class=HTMLResponse)
async def monitor_edit(request: Request, monitor_id: int):
    user = require_editor(request)
    db = SessionLocal()
    try:
        monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        if not monitor:
            return RedirectResponse(url="/monitors", status_code=303)
        groups = db.query(MonitorGroup).order_by(MonitorGroup.name).all()
        return templates.TemplateResponse("monitors/form.html", {"request": request, "user": user, "monitor": monitor, "monitor_types": [t.value for t in MonitorType], "groups": groups})
    finally:
        db.close()


@router.post("/{monitor_id}/edit")
async def monitor_update(
    request: Request,
    monitor_id: int,
    name: str = Form(...),
    type: str = Form(...),
    url: str = Form(...),
    port: str = Form(None),
    keyword: str = Form(None),
    group_id: str = Form(None),
    interval: int = Form(300),
    timeout: int = Form(30),
    http_method: str = Form("GET"),
    follow_redirects: str = Form(None),
    notification_email: str = Form(None),
    db: Session = Depends(get_db),
):
    user = require_editor(request)
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if not monitor:
        return RedirectResponse(url="/monitors", status_code=303)
    port_val = int(port) if port and port.strip() else None
    group_val = int(group_id) if group_id and group_id.strip() else None
    monitor.name = name
    monitor.type = MonitorType(type)
    monitor.url = url
    monitor.port = port_val
    monitor.group_id = group_val
    monitor.keyword = keyword if keyword and keyword.strip() else None
    monitor.interval = max(5, interval)
    monitor.timeout = min(timeout, 120)
    monitor.http_method = http_method or "GET"
    monitor.follow_redirects = (follow_redirects == "on")
    monitor.notification_email = notification_email if notification_email and notification_email.strip() else None
    db.commit()
    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=303)


@router.post("/{monitor_id}/delete")
async def monitor_delete(request: Request, monitor_id: int, db: Session = Depends(get_db)):
    user = require_admin(request)
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if monitor:
        db.delete(monitor)
        db.commit()
    return RedirectResponse(url="/monitors", status_code=303)


@router.post("/{monitor_id}/toggle")
async def monitor_toggle(request: Request, monitor_id: int, db: Session = Depends(get_db)):
    user = require_editor(request)
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if monitor:
        monitor.is_active = not monitor.is_active
        if not monitor.is_active:
            monitor.status = MonitorStatus.paused
        else:
            monitor.status = MonitorStatus.pending
        db.commit()
    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=303)


@router.get("/{monitor_id}/api/logs")
async def monitor_api_logs(request: Request, monitor_id: int):
    from fastapi.responses import JSONResponse
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    db = SessionLocal()
    try:
        logs = db.query(MonitorLog).filter(MonitorLog.monitor_id == monitor_id).order_by(MonitorLog.checked_at.desc()).limit(50).all()
        data = [{"status": l.status.value, "response_time": l.response_time, "checked_at": l.checked_at.isoformat(), "status_code": l.status_code} for l in logs]
        return JSONResponse(list(reversed(data)))
    finally:
        db.close()
