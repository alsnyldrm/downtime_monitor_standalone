from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.dependencies import require_admin
from app.database import SessionLocal
from app.models.fcm_token import FcmToken
from app.firebase_helper import send_custom_notification

router = APIRouter(prefix="/notifications")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def notifications_page(request: Request):
    user = require_admin(request)
    db = SessionLocal()
    try:
        token_count = db.query(FcmToken).count()
        return templates.TemplateResponse("notifications/index.html", {
            "request": request,
            "user": user,
            "device_count": token_count,
        })
    finally:
        db.close()


@router.post("/send")
async def send_notification(request: Request):
    require_admin(request)
    body = await request.json()
    title = (body.get("title") or "").strip()
    message = (body.get("message") or "").strip()
    ntype = body.get("type", "info")

    if not title or not message:
        return JSONResponse({"error": "Başlık ve mesaj gerekli"}, status_code=400)
    if len(title) > 200:
        return JSONResponse({"error": "Başlık çok uzun (max 200)"}, status_code=400)
    if len(message) > 1000:
        return JSONResponse({"error": "Mesaj çok uzun (max 1000)"}, status_code=400)

    result = send_custom_notification(title, message, ntype)
    return JSONResponse(result)
