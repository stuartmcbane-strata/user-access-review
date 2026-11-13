import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _flag(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _list(name: str) -> list[str]:
    return [p.strip().lower() for p in _env(name).replace(";", ",").split(",") if p.strip()]


@dataclass
class Config:
    hibob_base_url: str = "https://api.hibob.com/v1"
    hibob_service_user_id: str = ""
    hibob_service_user_token: str = ""
    hibob_include_prehires: bool = True
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_signin_activity: str = "auto"
    microsoft_include_guests: bool = True
    microsoft_users_file: str = ""
    store_backend: str = "file"
    storage_connection_string: str = ""
    store_file: str = "data/store.json"
    auth_mode: str = "easyauth"
    dev_user: str = "dev.user@example.com"
    allowed_users: list[str] = field(default_factory=list)
    cache_minutes: int = 10

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            hibob_base_url=_env("HIBOB_BASE_URL", "https://api.hibob.com/v1") or "https://api.hibob.com/v1",
            hibob_service_user_id=_env("HIBOB_SERVICE_USER_ID"),
            hibob_service_user_token=_env("HIBOB_SERVICE_USER_TOKEN"),
            hibob_include_prehires=_flag("HIBOB_INCLUDE_PREHIRES", True),
            graph_tenant_id=_env("GRAPH_TENANT_ID") or _env("WEBSITE_AUTH_AAD_ALLOWED_TENANTS"),
            graph_client_id=_env("GRAPH_CLIENT_ID"),
            graph_client_secret=_env("GRAPH_CLIENT_SECRET") or _env("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET"),
            graph_signin_activity=(_env("GRAPH_SIGNIN_ACTIVITY", "auto") or "auto").lower(),
            microsoft_include_guests=_flag("MICROSOFT_INCLUDE_GUESTS", True),
            microsoft_users_file=_env("MICROSOFT_USERS_FILE"),
            store_backend=(_env("STORE_BACKEND", "file") or "file").lower(),
            storage_connection_string=_env("STORAGE_CONNECTION_STRING"),
            store_file=_env("STORE_FILE", "data/store.json") or "data/store.json",
            auth_mode=(_env("AUTH_MODE", "easyauth") or "easyauth").lower(),
            dev_user=_env("DEV_USER", "dev.user@example.com"),
            allowed_users=_list("ALLOWED_USERS"),
            cache_minutes=int(_env("CACHE_MINUTES", "10") or 10),
        )
