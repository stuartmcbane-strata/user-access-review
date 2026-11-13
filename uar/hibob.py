from dataclasses import dataclass

import requests

TIMEOUT = 60

FIELDS = [
    "root.id",
    "root.email",
    "root.displayName",
    "internal.status",
    "internal.lifecycleStatus",
    "internal.terminationDate",
    "work.startDate",
    "work.title",
    "work.department",
    "work.site",
]


@dataclass
class HiBobPerson:
    id: str
    email: str
    display_name: str
    status: str
    lifecycle: str
    start_date: str = ""
    termination_date: str = ""
    title: str = ""
    department: str = ""
    site: str = ""

    @property
    def is_active(self) -> bool:
        return self.status.lower() == "active"

    @property
    def is_prehire(self) -> bool:
        return not self.is_active and self.lifecycle.lower() == "hired"


class HiBobError(RuntimeError):
    pass


class HiBobClient:
    def __init__(self, base_url: str, service_user_id: str, token: str, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.auth = (service_user_id, token)

    def list_people(self) -> list[HiBobPerson]:
        """Everyone visible to the service user, including leavers (needs inactive-employee permission)."""
        body = {"fields": FIELDS, "showInactive": True, "humanReadable": "REPLACE"}
        resp = self.session.post(f"{self.base_url}/people/search", json=body, timeout=TIMEOUT)
        if resp.status_code != 200:
            raise HiBobError(f"HiBob people/search returned HTTP {resp.status_code}: {resp.text[:300]}")
        return [p for p in (parse_person(e) for e in resp.json().get("employees", [])) if p.email]


def parse_person(emp: dict) -> HiBobPerson:
    internal = emp.get("internal") or {}
    work = emp.get("work") or {}
    return HiBobPerson(
        id=str(emp.get("id") or ""),
        email=(emp.get("email") or "").strip().lower(),
        display_name=emp.get("displayName") or "",
        status=str(internal.get("status") or ""),
        lifecycle=str(internal.get("lifecycleStatus") or ""),
        start_date=str(work.get("startDate") or ""),
        termination_date=str(internal.get("terminationDate") or ""),
        title=str(work.get("title") or ""),
        department=str(work.get("department") or ""),
        site=str(work.get("site") or ""),
    )
