from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from fastapi import Request
from app.config import SAML_SETTINGS, FEDERATION_METADATA_URL
import httpx
import xml.etree.ElementTree as ET
import os
import logging

logger = logging.getLogger(__name__)

_idp_cert_cache = None


async def fetch_idp_certificate():
    global _idp_cert_cache
    if _idp_cert_cache:
        return _idp_cert_cache
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(FEDERATION_METADATA_URL)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {
                "md": "urn:oasis:names:tc:SAML:2.0:metadata",
                "ds": "http://www.w3.org/2000/09/xmldsig#"
            }
            cert_el = root.find(".//md:IDPSSODescriptor/md:KeyDescriptor[@use='signing']/ds:KeyInfo/ds:X509Data/ds:X509Certificate", ns)
            if cert_el is None:
                cert_el = root.find(".//md:IDPSSODescriptor/md:KeyDescriptor/ds:KeyInfo/ds:X509Data/ds:X509Certificate", ns)
            if cert_el is not None and cert_el.text:
                _idp_cert_cache = cert_el.text.strip()
                return _idp_cert_cache
    except Exception as e:
        logger.error(f"IdP sertifika alınamadı: {e}")
    return ""


def prepare_saml_request(request: Request):
    url_data = {
        "https": "on" if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https" else "off",
        "http_host": request.headers.get("x-forwarded-host", request.headers.get("host", "localhost")),
        "script_name": request.url.path,
        "server_port": request.headers.get("x-forwarded-port", str(request.url.port or 443)),
        "get_data": dict(request.query_params),
        "post_data": {}
    }
    return url_data


async def init_saml_auth(request: Request, post_data=None):
    cert = await fetch_idp_certificate()
    settings = SAML_SETTINGS.copy()
    if cert:
        settings["idp"] = {**settings["idp"], "x509cert": cert}

    req = prepare_saml_request(request)
    if post_data:
        req["post_data"] = post_data

    auth = OneLogin_Saml2_Auth(req, settings)
    return auth
