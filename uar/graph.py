import json
from dataclasses import dataclass, field

import requests

TIMEOUT = 60
GRAPH = "https://graph.microsoft.com/v1.0"

BASE_SELECT = [
    "id",
    "displayName",
    "userPrincipalName",
    "mail",
    "otherMails",
    "proxyAddresses",
    "accountEnabled",
    "userType",
    "createdDateTime",
    "jobTitle",
    "department",
    "assignedLicenses",
    "onPremisesSyncEnabled",
    "externalUserState",
]


@dataclass
class MicrosoftUser:
    id: str
    display_name: str
    upn: str
    mail: str = ""
    account_enabled: bool = True
    user_type: str = "Member"
    created: str = ""
    job_title: str = ""
    department: str = ""
    licensed: bool = False
    synced: bool = False
    external_state: str = ""
    last_sign_in: str = ""
    keys: set[str] = field(default_factory=set)

    @property
    def is_guest(self) -> bool:
        return self.user_type.lower() == "guest"


class GraphError(RuntimeError):
    pass


def parse_user(u: dict) -> MicrosoftUser:
    upn = (u.get("userPrincipalName") or "").lower()
    mail = (u.get("mail") or "").lower()
    keys = {k for k in (upn, mail) if k}
    for addr in u.get("proxyAddresses") or []:
        if addr.lower().startswith("smtp:"):
            keys.add(addr[5:].lower())
    keys.update(m.lower() for m in (u.get("otherMails") or []) if m)
    sign_in = u.get("signInActivity") or {}
    last = max(
        (sign_in.get(k) or "" for k in ("lastSignInDateTime", "lastNonInteractiveSignInDateTime", "lastSuccessfulSignInDateTime")),
        default="",
    )
    return MicrosoftUser(
        id=u.get("id") or "",
        display_name=u.get("displayName") or "",
        upn=upn,
        mail=mail,
        account_enabled=bool(u.get("accountEnabled")),
        user_type=u.get("userType") or "Member",
        created=(u.get("createdDateTime") or "")[:10],
        job_title=u.get("jobTitle") or "",
        department=u.get("department") or "",
        licensed=bool(u.get("assignedLicenses")),
        synced=bool(u.get("onPremisesSyncEnabled")),
        external_state=u.get("externalUserState") or "",
        last_sign_in=last[:10],
        keys=keys,
    )


class GraphClient:
    """App-only (client credentials) Microsoft Graph client; needs User.Read.All, optionally AuditLog.Read.All."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, signin_activity: str = "auto",
                 session: requests.Session | None = None):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.signin_activity = signin_activity
        self.session = session or requests.Session()
        self.notes: list[str] = []

    def _token(self) -> str:
        resp = self.session.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            raise GraphError(f"Microsoft sign-in for the app failed (HTTP {resp.status_code}): {_error_text(resp)}")
        return resp.json()["access_token"]

    def _fetch(self, token: str, select: list[str]) -> list[dict]:
        url = f"{GRAPH}/users"
        params: dict | None = {"$select": ",".join(select), "$top": "999"}
        users: list[dict] = []
        while url:
            resp = self.session.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
            if resp.status_code != 200:
                raise GraphError(f"Microsoft Graph /users returned HTTP {resp.status_code}: {_error_text(resp)}")
            data = resp.json()
            users.extend(data.get("value", []))
            url, params = data.get("@odata.nextLink"), None
        return users

    def list_users(self) -> list[MicrosoftUser]:
        token = self._token()
        self.notes = []
        if self.signin_activity in ("auto", "on", "true", "yes"):
            try:
                raw = self._fetch(token, BASE_SELECT + ["signInActivity"])
            except GraphError as exc:
                if self.signin_activity != "auto":
                    raise
                self.notes.append(
                    "Last sign-in dates unavailable (needs AuditLog.Read.All and Entra ID P1): " + str(exc)[:200]
                )
                raw = self._fetch(token, BASE_SELECT)
        else:
            raw = self._fetch(token, BASE_SELECT)
        return [parse_user(u) for u in raw]


class FileMicrosoftSource:
    """Reads Graph-shaped user JSON ({"value": [...]} or a list) from disk, for local development."""

    def __init__(self, path: str):
        self.path = path
        self.notes = [f"Microsoft users loaded from local file {path} (not live Graph)."]

    def list_users(self) -> list[MicrosoftUser]:
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        rows = data.get("value", []) if isinstance(data, dict) else data
        return [parse_user(u) for u in rows]


def _error_text(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    err = body.get("error")
    if isinstance(err, dict):
        return f"{err.get('code')}: {err.get('message')}"[:300]
    return (body.get("error_description") or str(body))[:300]
