import logging
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
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
from passlib.hash import bcrypt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FBU Downtime Monitor", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400)

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
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                email="admin@local",
                display_name="Yönetici",
                password_hash=bcrypt.hash("admin"),
                role=UserRole.admin,
                auth_provider=AuthProvider.local,
                must_change_password=True,
                is_active=True,
            )
            db.add(admin)
            db.commit()
            logger.info("Varsayılan admin hesabı oluşturuldu (admin/admin)")
    finally:
        db.close()
    start_scheduler()
    init_firebase()
    logger.info("Monitor zamanlayıcı başlatıldı")
