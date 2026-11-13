import base64
import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from flask import Request


@dataclass
class Principal:
    name: str
    display_name: str = ""
    object_id: str = ""


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _claims(header: str) -> dict:
    try:
        data = json.loads(base64.b64decode(header + "=" * (-len(header) % 4)))
    except (ValueError, TypeError):
        return {}
    return {c.get("typ"): c.get("val") for c in data.get("claims", []) if isinstance(c, dict)}


def current_principal(request: Request, cfg) -> Principal:
    """Identify the signed-in user.

    In easyauth mode the identity comes from App Service Authentication (Entra ID), which strips any client-sent
    X-MS-CLIENT-PRINCIPAL* headers and injects its own. Refuse to trust them if App Service auth is not on.
    """
    if cfg.auth_mode == "dev":
        return Principal(name=cfg.dev_user.lower(), display_name="Local developer")
    if cfg.auth_mode != "easyauth":
        raise AuthError(500, f"Unknown AUTH_MODE {cfg.auth_mode!r}")
    if os.environ.get("WEBSITE_SITE_NAME") and os.environ.get("WEBSITE_AUTH_ENABLED", "").lower() != "true":
        raise AuthError(500, "App Service Authentication is not enabled on this web app; refusing to serve.")
    name = (request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME") or "").strip().lower()
    if not name:
        raise AuthError(401, "Not signed in.")
    claims = _claims(request.headers.get("X-MS-CLIENT-PRINCIPAL", ""))
    principal = Principal(
        name=name,
        display_name=claims.get("name") or name,
        object_id=request.headers.get("X-MS-CLIENT-PRINCIPAL-ID", ""),
    )
    if cfg.allowed_users and principal.name not in cfg.allowed_users:
        raise AuthError(403, f"{principal.name} is not allowed to use this tool.")
    return principal


def same_origin(request: Request) -> bool:
    """CSRF guard for form posts: the Origin (or Referer) must be this site."""
    source = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if not source:
        return False
    return urlparse(source).netloc.lower() == request.host.lower()
