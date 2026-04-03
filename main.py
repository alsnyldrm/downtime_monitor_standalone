import logging
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import SECRET_KEY
from app.database import engine, Base, SessionLocal
from app.dependencies import AuthMiddleware
from app.models import User, Monitor, MonitorLog, Incident
from app.models.monitor_group import MonitorGroup  # noqa: F401
from app.models.user import UserRole, AuthProvider
from app.routers import auth, dashboard, monitors, users, reports, groups, tools
from app.routers import notifications
from app.routers.api import router as api_router
from app.monitor_service import start_scheduler
from app.firebase_helper import init_firebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FBU Downtime Monitor", docs_url=None, redoc_url=None, openapi_url=None)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ── Security Headers Middleware ──
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'"
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400,
                   same_site="lax", https_only=True)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(monitors.router)
app.include_router(users.router)
app.include_router(reports.router)
app.include_router(groups.router)
app.include_router(tools.router)
app.include_router(notifications.router)
app.include_router(api_router)


@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    # Alembic migration'ları çalıştır
    from alembic.config import Config
    from alembic import command
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    # Local admin kullanıcıları devre dışı bırak
    db = SessionLocal()
    try:
        local_users = db.query(User).filter(User.auth_provider == AuthProvider.local).all()
        for u in local_users:
            if u.is_active:
                u.is_active = False
                logger.info(f"Local kullanıcı devre dışı bırakıldı: {u.username}")
        db.commit()
    finally:
        db.close()
    start_scheduler()
    init_firebase()
    logger.info("Monitor zamanlayıcı başlatıldı")
