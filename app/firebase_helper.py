import logging
import os
import firebase_admin
from firebase_admin import credentials, messaging
from app.database import SessionLocal
from app.models.fcm_token import FcmToken

logger = logging.getLogger(__name__)

_initialized = False


def init_firebase():
    global _initialized
    if _initialized:
        return
    cred_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "firebase-service-account.json")
    if not os.path.exists(cred_path):
        logger.warning("firebase-service-account.json bulunamadı, push bildirimler devre dışı")
        return
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
    _initialized = True
    logger.info("Firebase Admin SDK başlatıldı")


def send_push_notification(monitor_name: str, is_down: bool, reason: str = None):
    if not _initialized:
        return
    db = SessionLocal()
    try:
        tokens = db.query(FcmToken.token).all()
        token_list = [t[0] for t in tokens]
        if not token_list:
            return

        if is_down:
            title = f"🔴 {monitor_name} Çöktü!"
            body = reason or "Monitör yanıt vermiyor"
            ntype = "incident"
        else:
            title = f"🟢 {monitor_name} Düzeldi"
            body = "Monitör tekrar çalışıyor"
            ntype = "recovery"

        message = messaging.MulticastMessage(
            data={"title": title, "body": body, "type": ntype},
            tokens=token_list,
        )
        response = messaging.send_each_for_multicast(message)
        logger.info(f"Push gönderildi: {response.success_count} başarılı, {response.failure_count} başarısız")

        # Remove invalid tokens
        if response.failure_count > 0:
            for i, send_resp in enumerate(response.responses):
                if send_resp.exception:
                    db.query(FcmToken).filter(FcmToken.token == token_list[i]).delete()
            db.commit()
    except Exception as e:
        logger.error(f"Push bildirim hatası: {e}")
    finally:
        db.close()


def send_custom_notification(title: str, body: str, ntype: str = "info"):
    if not _initialized:
        return {"error": "Firebase başlatılmadı", "success": 0, "failure": 0}
    db = SessionLocal()
    try:
        tokens = db.query(FcmToken.token).all()
        token_list = [t[0] for t in tokens]
        if not token_list:
            return {"error": "Kayıtlı cihaz yok", "success": 0, "failure": 0}

        message = messaging.MulticastMessage(
            data={"title": title, "body": body, "type": ntype},
            tokens=token_list,
        )
        response = messaging.send_each_for_multicast(message)
        logger.info(f"Özel push gönderildi: {response.success_count} başarılı, {response.failure_count} başarısız")

        if response.failure_count > 0:
            for i, send_resp in enumerate(response.responses):
                if send_resp.exception:
                    db.query(FcmToken).filter(FcmToken.token == token_list[i]).delete()
            db.commit()

        return {
            "success": response.success_count,
            "failure": response.failure_count,
            "total": len(token_list),
        }
    except Exception as e:
        logger.error(f"Özel push bildirim hatası: {e}")
        return {"error": str(e), "success": 0, "failure": 0}
    finally:
        db.close()
