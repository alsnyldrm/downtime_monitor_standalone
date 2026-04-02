import os

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required. Create a .env file or set it in your environment.")

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required.")

APP_URL = os.getenv("APP_URL", "https://downtime.fbu.edu.tr")

SAML_SETTINGS = {
    "strict": True,
    "debug": os.getenv("SAML_DEBUG", "false").lower() == "true",
    "sp": {
        "entityId": APP_URL,
        "assertionConsumerService": {
            "url": f"{APP_URL}/saml/acs",
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        },
        "singleLogoutService": {
            "url": f"{APP_URL}/saml/sls",
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        },
        "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
    },
    "idp": {
        "entityId": "https://sts.windows.net/dc718077-bfeb-4008-8a36-f0633b36a83e/",
        "singleSignOnService": {
            "url": "https://login.microsoftonline.com/dc718077-bfeb-4008-8a36-f0633b36a83e/saml2",
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        },
        "singleLogoutService": {
            "url": "https://login.microsoftonline.com/dc718077-bfeb-4008-8a36-f0633b36a83e/saml2",
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        },
        "x509cert": ""
    },
    "security": {
        "nameIdEncrypted": False,
        "authnRequestsSigned": False,
        "logoutRequestSigned": False,
        "logoutResponseSigned": False,
        "signMetadata": False,
        "wantMessagesSigned": False,
        "wantAssertionsSigned": False,
        "wantNameId": True,
        "wantNameIdEncrypted": False,
        "wantAssertionsEncrypted": False,
        "allowSingleLabelDomains": False,
        "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
        "requestedAuthnContext": False
    }
}

FEDERATION_METADATA_URL = os.getenv("FEDERATION_METADATA_URL", "")

MONITOR_CHECK_INTERVAL = int(os.getenv("MONITOR_CHECK_INTERVAL", "300"))
