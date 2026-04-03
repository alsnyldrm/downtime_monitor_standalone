from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
import jwt as pyjwt
from app.database import get_db
from app import templates
from app.dependencies import get_current_user
from app.models.user import User, AuthProvider, UserRole
from app.saml_helper import prepare_saml_request, fetch_idp_certificate
from app.config import SAML_SETTINGS, SECRET_KEY
from onelogin.saml2.auth import OneLogin_Saml2_Auth
import copy
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 72

# İzin verilen email domain'leri
ALLOWED_EMAIL_DOMAINS = {"fbu.edu.tr"}

def _create_mobile_token(user_id: int) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)
    error = request.query_params.get("error")
    return templates.TemplateResponse("auth/login.html", {"request": request, "error": error})


# Local login devre dışı - sadece SAML
@router.post("/login")
async def login_post(request: Request):
    return RedirectResponse(url="/login?error=Yerel+giriş+devre+dışı.+Lütfen+Microsoft+ile+giriş+yapın.", status_code=303)


@router.get("/saml/login")
async def saml_login(request: Request):
    cert = await fetch_idp_certificate()
    if not cert:
        return RedirectResponse(url="/login?error=IdP+sertifikası+alınamadı", status_code=303)
    settings = copy.deepcopy(SAML_SETTINGS)
    settings["idp"]["x509cert"] = cert
    req = prepare_saml_request(request)
    auth = OneLogin_Saml2_Auth(req, settings)
    sso_url = auth.login()
    return RedirectResponse(url=sso_url)


@router.get("/api/v1/auth/saml/login")
async def saml_login_mobile(request: Request):
    cert = await fetch_idp_certificate()
    if not cert:
        return HTMLResponse(_mobile_error_page("IdP sertifikası alınamadı"))
    settings = copy.deepcopy(SAML_SETTINGS)
    settings["idp"]["x509cert"] = cert
    req = prepare_saml_request(request)
    auth = OneLogin_Saml2_Auth(req, settings)
    sso_url = auth.login(return_to="mobile")
    return RedirectResponse(url=sso_url)


def _is_allowed_email(email: str) -> bool:
    """Email domain'inin izin verilen listede olup olmadığını kontrol et."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].lower()
    return domain in ALLOWED_EMAIL_DOMAINS


@router.post("/saml/acs")
async def saml_acs(request: Request, db: Session = Depends(get_db)):
    cert = await fetch_idp_certificate()
    if not cert:
        return RedirectResponse(url="/login?error=IdP+sertifikası+alınamadı", status_code=303)
    settings = copy.deepcopy(SAML_SETTINGS)
    settings["idp"]["x509cert"] = cert
    req = prepare_saml_request(request)
    form_data = await request.form()
    req["post_data"] = dict(form_data)
    auth = OneLogin_Saml2_Auth(req, settings)
    auth.process_response()
    errors = auth.get_errors()

    relay_state = form_data.get("RelayState", "")
    is_mobile = relay_state == "mobile"

    if errors:
        logger.error(f"SAML hata: {errors}, reason: {auth.get_last_error_reason()}")
        if is_mobile:
            return HTMLResponse(_mobile_error_page("SAML doğrulama hatası"))
        return RedirectResponse(url="/login?error=SAML+doğrulama+hatası", status_code=303)

    attrs = auth.get_attributes()
    name_id = auth.get_nameid()
    email = name_id or attrs.get("http://schemas.xmlformats.org/ws/2005/05/identity/claims/emailaddress", [None])[0]
    display = attrs.get("http://schemas.microsoft.com/identity/claims/displayname", [email])[0]

    if not email:
        if is_mobile:
            return HTMLResponse(_mobile_error_page("Email bilgisi alınamadı"))
        return RedirectResponse(url="/login?error=Email+bilgisi+alınamadı", status_code=303)

    # Domain kısıtlaması
    if not _is_allowed_email(email):
        logger.warning(f"İzin verilmeyen domain ile giriş denemesi: {email}")
        if is_mobile:
            return HTMLResponse(_mobile_error_page("Bu email domain'i ile giriş yapılamaz"))
        return RedirectResponse(url="/login?error=Bu+email+domaini+ile+giriş+yapılamaz", status_code=303)

    user = db.query(User).filter(User.email == email).first()
    if not user:
        username = email.split("@")[0] if email else name_id
        user = User(
            username=username,
            email=email,
            display_name=display,
            role=UserRole.readonly,
            auth_provider=AuthProvider.saml,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.is_active:
        if is_mobile:
            return HTMLResponse(_mobile_error_page("Hesap devre dışı"))
        return RedirectResponse(url="/login?error=Hesap+devre+dışı", status_code=303)

    if is_mobile:
        token = _create_mobile_token(user.id)
        import json
        user_json = json.dumps({
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "role": user.role.value,
        })
        return HTMLResponse(_mobile_success_page(token, user_json))

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


def _html_escape(s: str) -> str:
    """Escape HTML special characters to prevent XSS."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#x27;"))


def _mobile_success_page(token: str, user_json: str) -> str:
    safe_token = _html_escape(token)
    safe_user = _html_escape(user_json)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="saml-token" content="{safe_token}">
<meta name="saml-user" content="{safe_user}">
<title>SAML OK</title></head>
<body><p>Giriş başarılı, uygulama yönlendiriliyor...</p></body></html>"""


def _mobile_error_page(error: str) -> str:
    safe_error = _html_escape(error)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="saml-error" content="{safe_error}">
<title>SAML Error</title></head>
<body><p>{safe_error}</p></body></html>"""


@router.get("/saml/metadata")
async def saml_metadata(request: Request):
    cert = await fetch_idp_certificate()
    settings = copy.deepcopy(SAML_SETTINGS)
    settings["idp"]["x509cert"] = cert
    req = prepare_saml_request(request)
    auth = OneLogin_Saml2_Auth(req, settings)
    metadata = auth.get_settings().get_sp_metadata()
    from fastapi.responses import Response
    return Response(content=metadata, media_type="application/xml")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
