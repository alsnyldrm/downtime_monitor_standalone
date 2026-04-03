from fastapi.templating import Jinja2Templates
from datetime import timedelta

templates = Jinja2Templates(directory="app/templates")


def _to_local(dt, fmt="%d.%m %H:%M:%S", offset=3):
    """UTC datetime'ı verilen offset'e göre formatla."""
    if dt is None:
        return ""
    return (dt + timedelta(hours=offset)).strftime(fmt)


templates.env.filters["localtime"] = _to_local
