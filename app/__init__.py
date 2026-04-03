from fastapi.templating import Jinja2Templates
from datetime import timedelta

templates = Jinja2Templates(directory="app/templates")


def _to_local(dt, fmt="%d.%m %H:%M:%S"):
    """UTC datetime'ı UTC+3 (Türkiye) olarak formatla."""
    if dt is None:
        return ""
    return (dt + timedelta(hours=3)).strftime(fmt)


templates.env.filters["localtime"] = _to_local
