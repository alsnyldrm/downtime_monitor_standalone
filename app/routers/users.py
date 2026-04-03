from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app import templates
from sqlalchemy.orm import Session
from passlib.hash import bcrypt
from app.database import get_db, SessionLocal
from app.dependencies import require_admin, require_login
from app.models.user import User, UserRole, AuthProvider

router = APIRouter(prefix="/users")


@router.get("/", response_class=HTMLResponse)
async def user_list(request: Request):
    user = require_admin(request)
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        return templates.TemplateResponse("users/list.html", {"request": request, "user": user, "users": users})
    finally:
        db.close()


@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def user_edit(request: Request, user_id: int):
    admin = require_admin(request)
    db = SessionLocal()
    try:
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            return RedirectResponse(url="/users", status_code=303)
        roles = [r.value for r in UserRole]
        return templates.TemplateResponse("users/edit.html", {"request": request, "user": admin, "target": target, "roles": roles})
    finally:
        db.close()


@router.post("/{user_id}/edit")
async def user_update(
    request: Request,
    user_id: int,
    role: str = Form(...),
    is_active: str = Form("off"),
    display_name: str = Form(None),
    db: Session = Depends(get_db),
):
    admin = require_admin(request)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/users", status_code=303)
    target.role = UserRole(role)
    target.is_active = is_active == "on"
    if display_name:
        target.display_name = display_name
    db.commit()
    return RedirectResponse(url="/users", status_code=303)


@router.post("/{user_id}/delete")
async def user_delete(request: Request, user_id: int, db: Session = Depends(get_db)):
    admin = require_admin(request)
    if admin.id == user_id:
        return RedirectResponse(url="/users", status_code=303)
    target = db.query(User).filter(User.id == user_id).first()
    if target:
        db.delete(target)
        db.commit()
    return RedirectResponse(url="/users", status_code=303)
