"""
Mobile API endpoints with JWT authentication.
All endpoints prefixed with /api/v1/
"""
from fastapi import APIRouter, Depends, HTTPException, Body, Request, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from typing import Optional
import jwt
import csv
import io
from passlib.hash import bcrypt

from app.config import SECRET_KEY
from app.database import SessionLocal
from app.models.user import User, UserRole
from app.models.monitor import Monitor, MonitorStatus
from app.models.monitor_log import MonitorLog, LogStatus
from app.models.monitor_group import MonitorGroup
from app.models.incident import Incident
from app.models.fcm_token import FcmToken

router = APIRouter(prefix="/api/v1")

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 72


# ── Auth helpers ──────────────────────────────────────────────

def create_token(user_id: int) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def get_current_api_user(token: str = Depends(lambda: None)):
    """Will be overridden per-request via header extraction."""
    pass


def _extract_user(authorization: Optional[str]) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token gerekli")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token süresi dolmuş")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Geçersiz token")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == payload["sub"], User.is_active == True).first()
        if not user:
            raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")
        return user
    finally:
        db.close()


def _db():
    return SessionLocal()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LoginRequest(BaseModel):
    username: str
    password: str

class MonitorUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    url: Optional[str] = None
    port: Optional[int] = None
    interval: Optional[int] = None
    timeout: Optional[int] = None
    http_method: Optional[str] = None
    follow_redirects: Optional[bool] = None
    keyword: Optional[str] = None
    group_id: Optional[int] = None
    notification_email: Optional[str] = None

class GroupBulkSettingsRequest(BaseModel):
    interval: Optional[int] = None
    timeout: Optional[int] = None
    http_method: Optional[str] = None
    follow_redirects: Optional[bool] = None
    notification_email: Optional[str] = None
    is_active: Optional[bool] = None


# ── Login ─────────────────────────────────────────────────────

@router.post("/auth/login")
async def api_login(req: LoginRequest):
    db = _db()
    try:
        user = db.query(User).filter(
            User.username == req.username,
            User.is_active == True
        ).first()
        if not user or not user.password_hash:
            raise HTTPException(status_code=401, detail="Geçersiz kullanıcı adı veya şifre")
        if not bcrypt.verify(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Geçersiz kullanıcı adı veya şifre")
        token = create_token(user.id)
        return {
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "role": user.role.value,
            }
        }
    finally:
        db.close()


@router.get("/auth/me")
async def api_me(authorization: Optional[str] = Header(None)):
    user = _extract_user(authorization)
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role.value,
    }


# ── Dashboard ─────────────────────────────────────────────────

@router.get("/dashboard")
async def api_dashboard(authorization: Optional[str] = Header(None)):
    _extract_user(authorization)
    db = _db()
    try:
        now = _now()
        day_ago = now - timedelta(hours=24)

        monitors = db.query(Monitor).filter(Monitor.is_active == True).all()
        total = len(monitors)
        up_count = sum(1 for m in monitors if m.status == MonitorStatus.up)
        down_count = sum(1 for m in monitors if m.status == MonitorStatus.down)
        paused_count = sum(1 for m in monitors if m.status == MonitorStatus.paused)
        pending_count = sum(1 for m in monitors if m.status == MonitorStatus.pending)

        avg_rt = db.query(func.avg(MonitorLog.response_time)).filter(
            MonitorLog.checked_at >= day_ago, MonitorLog.status == LogStatus.up
        ).scalar()

        active_incidents_count = db.query(Incident).filter(Incident.ended_at == None).count()

        checks_24h = db.query(func.count(MonitorLog.id)).filter(MonitorLog.checked_at >= day_ago).scalar() or 0
        failures_24h = db.query(func.count(MonitorLog.id)).filter(
            MonitorLog.checked_at >= day_ago, MonitorLog.status == LogStatus.down
        ).scalar() or 0
        success_rate_24h = ((checks_24h - failures_24h) / checks_24h * 100) if checks_24h > 0 else None

        recent_incidents = db.query(Incident).order_by(Incident.started_at.desc()).limit(10).all()

        monitor_data = []
        for m in monitors:
            last_logs = db.query(MonitorLog).filter(MonitorLog.monitor_id == m.id).order_by(
                MonitorLog.checked_at.desc()
            ).limit(50).all()
            monitor_data.append({
                "id": m.id,
                "name": m.name,
                "type": m.type.value,
                "url": m.url,
                "status": m.status.value if m.status else "pending",
                "uptime_percentage": m.uptime_percentage or 0,
                "last_response_time": m.last_response_time,
                "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
                "logs": [{"status": l.status.value, "checked_at": l.checked_at.isoformat()} for l in reversed(last_logs)],
            })

        return {
            "total": total,
            "up_count": up_count,
            "down_count": down_count,
            "paused_count": paused_count,
            "pending_count": pending_count,
            "avg_response_time": round(avg_rt, 1) if avg_rt else None,
            "active_incidents_count": active_incidents_count,
            "checks_24h": checks_24h,
            "failures_24h": failures_24h,
            "success_rate_24h": round(success_rate_24h, 1) if success_rate_24h is not None else None,
            "monitors": monitor_data,
            "recent_incidents": [
                {
                    "id": inc.id,
                    "monitor_name": inc.monitor.name if inc.monitor else "-",
                    "started_at": inc.started_at.isoformat(),
                    "ended_at": inc.ended_at.isoformat() if inc.ended_at else None,
                    "duration_seconds": inc.duration_seconds,
                    "reason": inc.reason,
                }
                for inc in recent_incidents
            ],
        }
    finally:
        db.close()


# ── Monitors ──────────────────────────────────────────────────

@router.get("/monitors")
async def api_monitors(authorization: Optional[str] = Header(None)):
    _extract_user(authorization)
    db = _db()
    try:
        monitors = db.query(Monitor).order_by(Monitor.name).all()
        return [
            {
                "id": m.id,
                "name": m.name,
                "type": m.type.value,
                "url": m.url,
                "port": m.port,
                "status": m.status.value if m.status else "pending",
                "is_active": m.is_active,
                "interval": m.interval,
                "timeout": m.timeout,
                "http_method": m.http_method,
                "follow_redirects": m.follow_redirects,
                "keyword": m.keyword,
                "group_id": m.group_id,
                "notification_email": m.notification_email,
                "uptime_percentage": m.uptime_percentage or 0,
                "last_response_time": m.last_response_time,
                "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
            }
            for m in monitors
        ]
    finally:
        db.close()


@router.get("/monitors/{monitor_id}")
async def api_monitor_detail(
    monitor_id: int,
    authorization: Optional[str] = Header(None),
):
    _extract_user(authorization)
    db = _db()
    try:
        m = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Monitör bulunamadı")
        logs = db.query(MonitorLog).filter(MonitorLog.monitor_id == m.id).order_by(
            MonitorLog.checked_at.desc()
        ).limit(100).all()
        incidents = db.query(Incident).filter(Incident.monitor_id == m.id).order_by(
            Incident.started_at.desc()
        ).limit(20).all()
        return {
            "id": m.id,
            "name": m.name,
            "type": m.type.value,
            "url": m.url,
            "port": m.port,
            "status": m.status.value if m.status else "pending",
            "is_active": m.is_active,
            "interval": m.interval,
            "timeout": m.timeout,
            "http_method": m.http_method,
            "follow_redirects": m.follow_redirects,
            "keyword": m.keyword,
            "group_id": m.group_id,
            "group_name": m.group.name if m.group else None,
            "notification_email": m.notification_email,
            "uptime_percentage": m.uptime_percentage or 0,
            "last_response_time": m.last_response_time,
            "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "logs": [
                {
                    "status": l.status.value,
                    "response_time": l.response_time,
                    "status_code": l.status_code,
                    "error_message": l.error_message,
                    "checked_at": l.checked_at.isoformat(),
                }
                for l in logs
            ],
            "incidents": [
                {
                    "id": inc.id,
                    "started_at": inc.started_at.isoformat(),
                    "ended_at": inc.ended_at.isoformat() if inc.ended_at else None,
                    "duration_seconds": inc.duration_seconds,
                    "reason": inc.reason,
                }
                for inc in incidents
            ],
        }
    finally:
        db.close()


@router.post("/monitors")
async def api_monitor_create(
    authorization: Optional[str] = Header(None),
    name: str = Body(...),
    type: str = Body(...),
    url: str = Body(...),
    port: Optional[int] = Body(None),
    interval: int = Body(60),
    timeout: int = Body(30),
    http_method: str = Body("GET"),
    follow_redirects: bool = Body(True),
    keyword: Optional[str] = Body(None),
    group_id: Optional[int] = Body(None),
    notification_email: Optional[str] = Body(None),
):
    user = _extract_user(authorization)
    if user.role.value not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    db = _db()
    try:
        m = Monitor(
            name=name, type=type, url=url, port=port,
            interval=max(5, min(86400, interval)),
            timeout=max(5, min(60, timeout)),
            http_method=http_method, follow_redirects=follow_redirects,
            keyword=keyword, group_id=group_id,
            notification_email=notification_email,
            created_by=user.id,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        return {"id": m.id, "message": "Monitör oluşturuldu"}
    finally:
        db.close()


@router.put("/monitors/{monitor_id}")
async def api_monitor_update(
    monitor_id: int,
    data: MonitorUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    user = _extract_user(authorization)
    if user.role.value not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    db = _db()
    try:
        m = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Monitör bulunamadı")
        if data.name is not None: m.name = data.name
        if data.type is not None: m.type = data.type
        if data.url is not None: m.url = data.url
        if data.port is not None: m.port = data.port
        if data.interval is not None: m.interval = max(5, min(86400, data.interval))
        if data.timeout is not None: m.timeout = max(5, min(60, data.timeout))
        if data.http_method is not None: m.http_method = data.http_method
        if data.follow_redirects is not None: m.follow_redirects = data.follow_redirects
        if data.keyword is not None: m.keyword = data.keyword
        if data.group_id is not None: m.group_id = data.group_id if data.group_id > 0 else None
        if data.notification_email is not None: m.notification_email = data.notification_email or None
        db.commit()
        return {"message": "Monitör güncellendi"}
    finally:
        db.close()


@router.delete("/monitors/{monitor_id}")
async def api_monitor_delete(
    monitor_id: int,
    authorization: Optional[str] = Header(None),
):
    user = _extract_user(authorization)
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    db = _db()
    try:
        m = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Monitör bulunamadı")
        db.delete(m)
        db.commit()
        return {"message": "Monitör silindi"}
    finally:
        db.close()


@router.post("/monitors/{monitor_id}/toggle")
async def api_monitor_toggle(
    monitor_id: int,
    authorization: Optional[str] = Header(None),
):
    user = _extract_user(authorization)
    if user.role.value not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    db = _db()
    try:
        m = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Monitör bulunamadı")
        m.is_active = not m.is_active
        if not m.is_active:
            m.status = MonitorStatus.paused
        else:
            m.status = MonitorStatus.pending
        db.commit()
        return {"is_active": m.is_active, "status": m.status.value}
    finally:
        db.close()


# ── Groups ────────────────────────────────────────────────────

@router.get("/groups")
async def api_groups(authorization: Optional[str] = Header(None)):
    _extract_user(authorization)
    db = _db()
    try:
        groups = db.query(MonitorGroup).order_by(MonitorGroup.name).all()
        ungrouped = db.query(Monitor).filter(Monitor.group_id == None, Monitor.is_active == True).count()
        return {
            "groups": [
                {
                    "id": g.id,
                    "name": g.name,
                    "description": g.description,
                    "monitor_count": len(g.monitors),
                    "up_count": sum(1 for m in g.monitors if m.status and m.status.value == "up"),
                    "down_count": sum(1 for m in g.monitors if m.status and m.status.value == "down"),
                }
                for g in groups
            ],
            "ungrouped_count": ungrouped,
        }
    finally:
        db.close()


@router.get("/groups/{group_id}")
async def api_group_detail(
    group_id: int,
    authorization: Optional[str] = Header(None),
):
    _extract_user(authorization)
    db = _db()
    try:
        group = db.query(MonitorGroup).filter(MonitorGroup.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Grup bulunamadı")
        monitors = db.query(Monitor).filter(Monitor.group_id == group_id).order_by(Monitor.name).all()
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "monitors": [
                {
                    "id": m.id,
                    "name": m.name,
                    "type": m.type.value,
                    "url": m.url,
                    "status": m.status.value if m.status else "pending",
                    "is_active": m.is_active,
                    "interval": m.interval,
                    "timeout": m.timeout,
                    "uptime_percentage": m.uptime_percentage or 0,
                    "last_response_time": m.last_response_time,
                }
                for m in monitors
            ],
        }
    finally:
        db.close()


@router.post("/groups")
async def api_group_create(
    authorization: Optional[str] = Header(None),
    name: str = Body(...),
    description: Optional[str] = Body(None),
):
    user = _extract_user(authorization)
    if user.role.value not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    db = _db()
    try:
        existing = db.query(MonitorGroup).filter(MonitorGroup.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Bu isimde bir grup zaten var")
        group = MonitorGroup(name=name, description=description, created_by=user.id)
        db.add(group)
        db.commit()
        db.refresh(group)
        return {"id": group.id, "message": "Grup oluşturuldu"}
    finally:
        db.close()


@router.put("/groups/{group_id}/settings")
async def api_group_bulk_settings(
    group_id: int,
    data: GroupBulkSettingsRequest,
    authorization: Optional[str] = Header(None),
):
    user = _extract_user(authorization)
    if user.role.value not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    db = _db()
    try:
        group = db.query(MonitorGroup).filter(MonitorGroup.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Grup bulunamadı")
        monitors = db.query(Monitor).filter(Monitor.group_id == group_id).all()
        for m in monitors:
            if data.interval is not None: m.interval = max(5, min(86400, data.interval))
            if data.timeout is not None: m.timeout = max(5, min(60, data.timeout))
            if data.http_method is not None: m.http_method = data.http_method
            if data.follow_redirects is not None: m.follow_redirects = data.follow_redirects
            if data.notification_email is not None: m.notification_email = data.notification_email or None
            if data.is_active is not None: m.is_active = data.is_active
        db.commit()
        return {"message": f"{len(monitors)} monitöre ayarlar uygulandı"}
    finally:
        db.close()


# ── Reports ───────────────────────────────────────────────────

@router.get("/reports")
async def api_reports(authorization: Optional[str] = Header(None)):
    _extract_user(authorization)
    db = _db()
    try:
        now = _now()
        day_ago = now - timedelta(hours=24)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        monitors = db.query(Monitor).order_by(Monitor.name).all()

        uptime_data = []
        for m in monitors:
            total_logs = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.monitor_id == m.id, MonitorLog.checked_at >= month_ago
            ).scalar() or 0
            up_logs = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.monitor_id == m.id, MonitorLog.checked_at >= month_ago,
                MonitorLog.status == LogStatus.up
            ).scalar() or 0
            uptime_pct = (up_logs / total_logs * 100) if total_logs > 0 else None
            avg_rt = db.query(func.avg(MonitorLog.response_time)).filter(
                MonitorLog.monitor_id == m.id, MonitorLog.checked_at >= month_ago,
                MonitorLog.status == LogStatus.up
            ).scalar()
            uptime_data.append({
                "monitor_id": m.id,
                "monitor_name": m.name,
                "total_checks": total_logs,
                "up_checks": up_logs,
                "uptime_pct": round(uptime_pct, 2) if uptime_pct else None,
                "avg_response_time": round(avg_rt, 1) if avg_rt else None,
            })

        active_incidents = db.query(Incident).filter(Incident.ended_at == None).count()
        total_incidents_30d = db.query(Incident).filter(Incident.started_at >= month_ago).count()
        avg_dur = db.query(func.avg(Incident.duration_seconds)).filter(
            Incident.started_at >= month_ago, Incident.duration_seconds != None
        ).scalar()

        checks_24h = db.query(func.count(MonitorLog.id)).filter(MonitorLog.checked_at >= day_ago).scalar() or 0
        failures_24h = db.query(func.count(MonitorLog.id)).filter(
            MonitorLog.checked_at >= day_ago, MonitorLog.status == LogStatus.down
        ).scalar() or 0
        checks_7d = db.query(func.count(MonitorLog.id)).filter(MonitorLog.checked_at >= week_ago).scalar() or 0
        failures_7d = db.query(func.count(MonitorLog.id)).filter(
            MonitorLog.checked_at >= week_ago, MonitorLog.status == LogStatus.down
        ).scalar() or 0

        recent_incidents = db.query(Incident).order_by(Incident.started_at.desc()).limit(20).all()

        daily_stats = []
        for i in range(6, -1, -1):
            day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            total = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.checked_at >= day_start, MonitorLog.checked_at < day_end
            ).scalar() or 0
            failures = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.checked_at >= day_start, MonitorLog.checked_at < day_end,
                MonitorLog.status == LogStatus.down
            ).scalar() or 0
            daily_stats.append({
                "date": day_start.strftime("%d.%m"),
                "total": total,
                "failures": failures,
                "success": total - failures,
            })

        # --- Slow monitors (top 5) ---
        slow_monitors = sorted(
            [u for u in uptime_data if u["avg_response_time"] is not None],
            key=lambda x: x["avg_response_time"], reverse=True
        )[:5]

        # --- Worst uptime monitors (top 5) ---
        worst_uptime = sorted(
            [u for u in uptime_data if u["uptime_pct"] is not None],
            key=lambda x: x["uptime_pct"]
        )[:5]

        # --- Hourly stats (last 24h) ---
        hourly_stats = []
        for i in range(23, -1, -1):
            hour_start = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
            hour_end = hour_start + timedelta(hours=1)
            total_h = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.checked_at >= hour_start, MonitorLog.checked_at < hour_end
            ).scalar() or 0
            failures_h = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.checked_at >= hour_start, MonitorLog.checked_at < hour_end,
                MonitorLog.status == LogStatus.down
            ).scalar() or 0
            hourly_stats.append({
                "hour": hour_start.strftime("%H:%M"),
                "total": total_h,
                "failures": failures_h,
                "success": total_h - failures_h,
            })

        # --- Response time trend per monitor (daily avg, last 7 days) ---
        response_time_trend = []
        for m in monitors:
            daily_rts = []
            for i in range(6, -1, -1):
                ds = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
                de = ds + timedelta(days=1)
                avg = db.query(func.avg(MonitorLog.response_time)).filter(
                    MonitorLog.monitor_id == m.id,
                    MonitorLog.checked_at >= ds, MonitorLog.checked_at < de,
                    MonitorLog.status == LogStatus.up
                ).scalar()
                daily_rts.append({
                    "date": ds.strftime("%d.%m"),
                    "avg_response_time": round(avg, 1) if avg else None,
                })
            response_time_trend.append({
                "monitor_id": m.id,
                "monitor_name": m.name,
                "daily": daily_rts,
            })

        # --- Group summary ---
        groups = db.query(MonitorGroup).all()
        group_stats = []
        for g in groups:
            g_monitors = [m for m in monitors if m.group_id == g.id]
            g_total = len(g_monitors)
            g_up = sum(1 for m in g_monitors if m.status and m.status.value == "up")
            g_down = sum(1 for m in g_monitors if m.status and m.status.value == "down")
            g_uptimes = [u["uptime_pct"] for u in uptime_data if u["uptime_pct"] is not None and any(m.id == u["monitor_id"] for m in g_monitors)]
            avg_uptime = round(sum(g_uptimes) / len(g_uptimes), 2) if g_uptimes else None
            group_stats.append({
                "group_id": g.id,
                "group_name": g.name,
                "total": g_total,
                "up": g_up,
                "down": g_down,
                "avg_uptime": avg_uptime,
            })

        # --- Monthly incident trend (last 6 months) ---
        monthly_incidents = []
        for i in range(5, -1, -1):
            month_start = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if i > 0:
                next_month = (month_start + timedelta(days=32)).replace(day=1)
            else:
                next_month = now
            count = db.query(func.count(Incident.id)).filter(
                Incident.started_at >= month_start, Incident.started_at < next_month
            ).scalar() or 0
            monthly_incidents.append({
                "month": month_start.strftime("%Y-%m"),
                "count": count,
            })

        return {
            "uptime_data": uptime_data,
            "active_incidents": active_incidents,
            "total_incidents_30d": total_incidents_30d,
            "avg_incident_duration_seconds": round(avg_dur) if avg_dur else None,
            "checks_24h": checks_24h,
            "failures_24h": failures_24h,
            "checks_7d": checks_7d,
            "failures_7d": failures_7d,
            "slow_monitors": slow_monitors,
            "worst_uptime": worst_uptime,
            "hourly_stats": hourly_stats,
            "response_time_trend": response_time_trend,
            "group_stats": group_stats,
            "monthly_incidents": monthly_incidents,
            "recent_incidents": [
                {
                    "id": inc.id,
                    "monitor_name": inc.monitor.name if inc.monitor else "-",
                    "started_at": inc.started_at.isoformat(),
                    "ended_at": inc.ended_at.isoformat() if inc.ended_at else None,
                    "duration_seconds": inc.duration_seconds,
                    "reason": inc.reason,
                }
                for inc in recent_incidents
            ],
            "daily_stats": daily_stats,
        }
    finally:
        db.close()


@router.get("/reports/export")
async def api_reports_export(
    format: str = Query("csv"),
    authorization: Optional[str] = Header(None),
):
    _extract_user(authorization)
    db = _db()
    try:
        now = _now()
        month_ago = now - timedelta(days=30)
        monitors = db.query(Monitor).order_by(Monitor.name).all()

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')

        # Sheet 1: Monitor Uptime Summary
        writer.writerow(["=== MONİTÖR UPTIME RAPORU (Son 30 Gün) ==="])
        writer.writerow(["Monitör", "Tip", "URL", "Grup", "Toplam Kontrol", "Başarılı", "Uptime %", "Ort. Yanıt (ms)", "Durum"])
        for m in monitors:
            total_logs = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.monitor_id == m.id, MonitorLog.checked_at >= month_ago
            ).scalar() or 0
            up_logs = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.monitor_id == m.id, MonitorLog.checked_at >= month_ago,
                MonitorLog.status == LogStatus.up
            ).scalar() or 0
            uptime_pct = round(up_logs / total_logs * 100, 2) if total_logs > 0 else 0
            avg_rt = db.query(func.avg(MonitorLog.response_time)).filter(
                MonitorLog.monitor_id == m.id, MonitorLog.checked_at >= month_ago,
                MonitorLog.status == LogStatus.up
            ).scalar()
            writer.writerow([
                m.name,
                m.type.value,
                m.url,
                m.group.name if m.group else "-",
                total_logs,
                up_logs,
                f"{uptime_pct}%",
                round(avg_rt, 1) if avg_rt else "-",
                m.status.value if m.status else "pending",
            ])

        writer.writerow([])
        writer.writerow(["=== OLAY GEÇMİŞİ (Son 30 Gün) ==="])
        writer.writerow(["Monitör", "Başlangıç", "Bitiş", "Süre (dk)", "Sebep"])
        incidents = db.query(Incident).filter(
            Incident.started_at >= month_ago
        ).order_by(Incident.started_at.desc()).all()
        for inc in incidents:
            duration_min = round(inc.duration_seconds / 60, 1) if inc.duration_seconds else "-"
            writer.writerow([
                inc.monitor.name if inc.monitor else "-",
                inc.started_at.strftime("%Y-%m-%d %H:%M"),
                inc.ended_at.strftime("%Y-%m-%d %H:%M") if inc.ended_at else "Devam ediyor",
                duration_min,
                inc.reason or "-",
            ])

        writer.writerow([])
        writer.writerow(["=== GÜNLÜK İSTATİSTİKLER (Son 7 Gün) ==="])
        writer.writerow(["Tarih", "Toplam Kontrol", "Başarılı", "Başarısız", "Başarı Oranı %"])
        for i in range(6, -1, -1):
            ds = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            de = ds + timedelta(days=1)
            total = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.checked_at >= ds, MonitorLog.checked_at < de
            ).scalar() or 0
            failures = db.query(func.count(MonitorLog.id)).filter(
                MonitorLog.checked_at >= ds, MonitorLog.checked_at < de,
                MonitorLog.status == LogStatus.down
            ).scalar() or 0
            rate = round((total - failures) / total * 100, 1) if total > 0 else 0
            writer.writerow([ds.strftime("%Y-%m-%d"), total, total - failures, failures, f"{rate}%"])

        output.seek(0)
        filename = f"rapor_{now.strftime('%Y%m%d_%H%M')}.csv"
        bom = b'\xef\xbb\xbf'
        content = bom + output.getvalue().encode('utf-8')
        from fastapi.responses import Response as RawResponse
        return RawResponse(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    finally:
        db.close()


# ── Tools ─────────────────────────────────────────────────────
# Tools endpoints already return JSON, but they use session auth.
# Re-expose them here with JWT auth.

@router.post("/tools/{tool_name}")
async def api_tool(
    tool_name: str,
    authorization: Optional[str] = Header(None),
    target: str = Body(..., embed=True),
):
    _extract_user(authorization)
    if tool_name not in ("dns", "ping", "port", "ssl", "headers", "traceroute", "whois", "subnet", "geoip", "rdns", "banner", "httpperf"):
        raise HTTPException(status_code=404, detail="Araç bulunamadı")
    return await _run_tool(tool_name, target)


async def _run_tool(tool_name: str, target: str):
    """Run network tools directly."""
    import subprocess
    import socket
    import ssl as ssl_lib
    import json

    if tool_name == "dns":
        import subprocess
        result = {}
        for rtype in ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]:
            try:
                out = subprocess.run(
                    ["dig", "+short", target, rtype],
                    capture_output=True, text=True, timeout=10
                )
                lines = [l.strip() for l in out.stdout.strip().split("\n") if l.strip()]
                if lines:
                    result[rtype] = lines
            except Exception:
                pass
        return {"target": target, "records": result}

    elif tool_name == "ping":
        try:
            out = subprocess.run(
                ["ping", "-c", "4", "-W", "5", target],
                capture_output=True, text=True, timeout=30
            )
            return {"target": target, "output": out.stdout, "success": out.returncode == 0}
        except Exception as e:
            return {"target": target, "output": str(e), "success": False}

    elif tool_name == "port":
        common_ports = [21, 22, 25, 53, 80, 110, 143, 443, 465, 587, 993, 995, 3306, 3389, 5432, 8080, 8443]
        results = []
        for p in common_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                r = s.connect_ex((target, p))
                results.append({"port": p, "open": r == 0})
                s.close()
            except Exception:
                results.append({"port": p, "open": False})
        return {"target": target, "ports": results}

    elif tool_name == "ssl":
        try:
            ctx = ssl_lib.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=target) as s:
                s.settimeout(10)
                s.connect((target, 443))
                cert = s.getpeercert()
            return {
                "target": target,
                "subject": dict(x[0] for x in cert.get("subject", ())),
                "issuer": dict(x[0] for x in cert.get("issuer", ())),
                "not_before": cert.get("notBefore"),
                "not_after": cert.get("notAfter"),
                "serial": cert.get("serialNumber"),
            }
        except Exception as e:
            return {"target": target, "error": str(e)}

    elif tool_name == "traceroute":
        try:
            out = subprocess.run(
                ["traceroute", "-m", "20", "-w", "3", target],
                capture_output=True, text=True, timeout=60
            )
            return {"target": target, "output": out.stdout}
        except Exception as e:
            return {"target": target, "output": str(e)}

    elif tool_name == "whois":
        try:
            out = subprocess.run(
                ["whois", target],
                capture_output=True, text=True, timeout=15
            )
            return {"target": target, "output": out.stdout}
        except Exception as e:
            return {"target": target, "output": str(e)}

    elif tool_name == "headers":
        import httpx
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                resp = await client.get(f"https://{target}" if not target.startswith("http") else target)
            headers_dict = dict(resp.headers)
            return {"target": target, "status_code": resp.status_code, "headers": headers_dict}
        except Exception as e:
            return {"target": target, "error": str(e)}

    return {"error": "Bilinmeyen araç"}


# ── Users (admin only) ───────────────────────────────────────

@router.get("/users")
async def api_users(authorization: Optional[str] = Header(None)):
    user = _extract_user(authorization)
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    db = _db()
    try:
        users = db.query(User).order_by(User.username).all()
        return [
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "email": u.email,
                "role": u.role.value,
                "auth_provider": u.auth_provider.value,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    finally:
        db.close()


# ── FCM Token Registration ───────────────────────────────────

class FcmTokenRequest(BaseModel):
    token: str

@router.post("/fcm/register")
def register_fcm_token(
    req: FcmTokenRequest,
    authorization: Optional[str] = Header(None),
):
    user = _extract_user(authorization)
    db = _db()
    try:
        existing = db.query(FcmToken).filter(FcmToken.token == req.token).first()
        if existing:
            existing.user_id = user.id
        else:
            db.add(FcmToken(user_id=user.id, token=req.token))
        db.commit()
        return {"status": "ok"}
    finally:
        db.close()
