from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.dependencies import require_login, require_editor, require_admin
from app.models.monitor_group import MonitorGroup
from app.models.monitor import Monitor
from typing import Optional

router = APIRouter(prefix="/groups")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def group_list(request: Request):
    user = require_login(request)
    db = SessionLocal()
    try:
        groups = db.query(MonitorGroup).order_by(MonitorGroup.name).all()
        ungrouped = db.query(Monitor).filter(Monitor.group_id == None, Monitor.is_active == True).count()
        return templates.TemplateResponse("groups/list.html", {
            "request": request, "user": user, "groups": groups, "ungrouped": ungrouped
        })
    finally:
        db.close()


@router.get("/new", response_class=HTMLResponse)
async def group_new(request: Request):
    user = require_editor(request)
    return templates.TemplateResponse("groups/form.html", {
        "request": request, "user": user, "group": None
    })


@router.post("/new")
async def group_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    db: Session = Depends(get_db),
):
    user = require_editor(request)
    existing = db.query(MonitorGroup).filter(MonitorGroup.name == name).first()
    if existing:
        return templates.TemplateResponse("groups/form.html", {
            "request": request, "user": user, "group": None,
            "error": "Bu isimde bir grup zaten var."
        })
    group = MonitorGroup(
        name=name,
        description=description if description and description.strip() else None,
        created_by=user.id,
    )
    db.add(group)
    db.commit()
    return RedirectResponse(url="/groups", status_code=303)


@router.get("/{group_id}", response_class=HTMLResponse)
async def group_detail(request: Request, group_id: int):
    user = require_login(request)
    db = SessionLocal()
    try:
        group = db.query(MonitorGroup).filter(MonitorGroup.id == group_id).first()
        if not group:
            return RedirectResponse(url="/groups", status_code=303)
        monitors = db.query(Monitor).filter(Monitor.group_id == group_id).order_by(Monitor.name).all()
        unassigned = db.query(Monitor).filter(
            (Monitor.group_id == None) | (Monitor.group_id != group_id)
        ).order_by(Monitor.name).all()
        return templates.TemplateResponse("groups/detail.html", {
            "request": request, "user": user, "group": group,
            "monitors": monitors, "unassigned": unassigned
        })
    finally:
        db.close()


@router.get("/{group_id}/edit", response_class=HTMLResponse)
async def group_edit(request: Request, group_id: int):
    user = require_editor(request)
    db = SessionLocal()
    try:
        group = db.query(MonitorGroup).filter(MonitorGroup.id == group_id).first()
        if not group:
            return RedirectResponse(url="/groups", status_code=303)
        return templates.TemplateResponse("groups/form.html", {
            "request": request, "user": user, "group": group
        })
    finally:
        db.close()


@router.post("/{group_id}/edit")
async def group_update(
    request: Request,
    group_id: int,
    name: str = Form(...),
    description: str = Form(None),
    db: Session = Depends(get_db),
):
    user = require_editor(request)
    group = db.query(MonitorGroup).filter(MonitorGroup.id == group_id).first()
    if not group:
        return RedirectResponse(url="/groups", status_code=303)
    existing = db.query(MonitorGroup).filter(MonitorGroup.name == name, MonitorGroup.id != group_id).first()
    if existing:
        return templates.TemplateResponse("groups/form.html", {
            "request": request, "user": user, "group": group,
            "error": "Bu isimde başka bir grup zaten var."
        })
    group.name = name
    group.description = description if description and description.strip() else None
    db.commit()
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)


@router.post("/{group_id}/delete")
async def group_delete(request: Request, group_id: int, db: Session = Depends(get_db)):
    user = require_admin(request)
    group = db.query(MonitorGroup).filter(MonitorGroup.id == group_id).first()
    if group:
        # Gruptaki monitörlerin group_id'sini NULL yap
        db.query(Monitor).filter(Monitor.group_id == group_id).update({"group_id": None})
        db.delete(group)
        db.commit()
    return RedirectResponse(url="/groups", status_code=303)


@router.post("/{group_id}/assign")
async def group_assign(
    request: Request,
    group_id: int,
    monitor_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = require_editor(request)
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if monitor:
        monitor.group_id = group_id
        db.commit()
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)


@router.post("/{group_id}/remove/{monitor_id}")
async def group_remove_monitor(
    request: Request,
    group_id: int,
    monitor_id: int,
    db: Session = Depends(get_db),
):
    user = require_editor(request)
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.group_id == group_id).first()
    if monitor:
        monitor.group_id = None
        db.commit()
    return RedirectResponse(url=f"/groups/{group_id}", status_code=303)


@router.get("/{group_id}/settings", response_class=HTMLResponse)
async def group_settings(request: Request, group_id: int):
    user = require_editor(request)
    db = SessionLocal()
    try:
        group = db.query(MonitorGroup).filter(MonitorGroup.id == group_id).first()
        if not group:
            return RedirectResponse(url="/groups", status_code=303)
        monitors = db.query(Monitor).filter(Monitor.group_id == group_id).order_by(Monitor.name).all()
        return templates.TemplateResponse("groups/settings.html", {
            "request": request, "user": user, "group": group, "monitors": monitors
        })
    finally:
        db.close()


@router.post("/{group_id}/settings")
async def group_settings_apply(
    request: Request,
    group_id: int,
    db: Session = Depends(get_db),
    apply_interval: Optional[str] = Form(None),
    interval: int = Form(60),
    apply_timeout: Optional[str] = Form(None),
    timeout: int = Form(30),
    apply_http_method: Optional[str] = Form(None),
    http_method: str = Form("GET"),
    apply_follow_redirects: Optional[str] = Form(None),
    follow_redirects: Optional[str] = Form(None),
    apply_notification_email: Optional[str] = Form(None),
    notification_email: Optional[str] = Form(None),
    apply_is_active: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
):
    user = require_editor(request)
    group = db.query(MonitorGroup).filter(MonitorGroup.id == group_id).first()
    if not group:
        return RedirectResponse(url="/groups", status_code=303)

    monitors = db.query(Monitor).filter(Monitor.group_id == group_id).all()
    updated_fields = []

    for m in monitors:
        if apply_interval:
            m.interval = max(5, min(86400, interval))
        if apply_timeout:
            m.timeout = max(5, min(60, timeout))
        if apply_http_method:
            m.http_method = http_method
        if apply_follow_redirects:
            m.follow_redirects = follow_redirects == "on"
        if apply_notification_email:
            m.notification_email = notification_email.strip() if notification_email and notification_email.strip() else None
        if apply_is_active:
            m.is_active = is_active == "on"

    if apply_interval:
        updated_fields.append("Kontrol aralığı")
    if apply_timeout:
        updated_fields.append("Zaman aşımı")
    if apply_http_method:
        updated_fields.append("HTTP metodu")
    if apply_follow_redirects:
        updated_fields.append("Yönlendirme takibi")
    if apply_notification_email:
        updated_fields.append("Bildirim e-postası")
    if apply_is_active:
        updated_fields.append("Aktiflik durumu")

    db.commit()

    monitors = db.query(Monitor).filter(Monitor.group_id == group_id).order_by(Monitor.name).all()
    success_msg = f"{len(monitors)} monitöre uygulandı: {', '.join(updated_fields)}" if updated_fields else "Hiçbir ayar seçilmedi."

    return templates.TemplateResponse("groups/settings.html", {
        "request": request, "user": user, "group": group,
        "monitors": monitors, "success": success_msg
    })
