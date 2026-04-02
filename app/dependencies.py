from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.database import SessionLocal
from app.models.user import User


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        return user
    finally:
        db.close()


def require_login(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(request: Request):
    user = get_current_user(request)
    if not user or user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    return user


def require_editor(request: Request):
    user = get_current_user(request)
    if not user or user.role.value not in ("admin", "editor"):
        raise HTTPException(status_code=403, detail="Yetkiniz yok")
    return user


class AuthMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {"/login", "/saml/acs", "/saml/login", "/saml/metadata", "/saml/sls", "/static", "/favicon.ico", "/api/v1"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login", status_code=303)

        # Check must_change_password
        if path != "/change-password" and path != "/logout":
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if user and user.must_change_password:
                    return RedirectResponse(url="/change-password", status_code=303)
            finally:
                db.close()

        return await call_next(request)
