import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timezone

CATEGORIES = [
    "External / guest",
    "Contractor",
    "Service account",
    "Shared mailbox",
    "Room / resource",
    "Admin / break-glass",
    "Other",
]


@dataclass
class AdditionalUser:
    id: str
    identifier: str
    display_name: str = ""
    category: str = "Other"
    reason: str = ""
    sponsor: str = ""
    expires: str = ""
    ms_object_id: str = ""
    added_by: str = ""
    added_at: str = ""
    updated_by: str = ""
    updated_at: str = ""

    def is_expired(self, today: date | None = None) -> bool:
        if not self.expires:
            return False
        try:
            return date.fromisoformat(self.expires) < (today or date.today())
        except ValueError:
            return False

    @classmethod
    def from_dict(cls, d: dict) -> "AdditionalUser":
        names = {f.name for f in fields(cls)}
        return cls(**{k: ("" if d.get(k) is None else str(d.get(k))) for k in names if k in d})


@dataclass
class AuditEvent:
    at: str
    actor: str
    action: str
    identifier: str
    details: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return uuid.uuid4().hex


class FileStore:
    """JSON file store for local development."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"additional": [], "audit": []}
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, self.path)

    def list_additional(self) -> list[AdditionalUser]:
        with self._lock:
            return [AdditionalUser.from_dict(d) for d in self._load()["additional"]]

    def get_additional(self, entry_id: str) -> AdditionalUser | None:
        return next((e for e in self.list_additional() if e.id == entry_id), None)

    def save_additional(self, entry: AdditionalUser) -> None:
        with self._lock:
            data = self._load()
            data["additional"] = [d for d in data["additional"] if d.get("id") != entry.id] + [asdict(entry)]
            self._save(data)

    def delete_additional(self, entry_id: str) -> None:
        with self._lock:
            data = self._load()
            data["additional"] = [d for d in data["additional"] if d.get("id") != entry_id]
            self._save(data)

    def add_audit(self, event: AuditEvent) -> None:
        with self._lock:
            data = self._load()
            data["audit"].append(asdict(event))
            self._save(data)

    def list_audit(self, limit: int = 500) -> list[AuditEvent]:
        with self._lock:
            rows = self._load()["audit"]
        return [AuditEvent(**r) for r in sorted(rows, key=lambda r: r["at"], reverse=True)[:limit]]


class TableStore:
    """Azure Table Storage: tables AdditionalUsers and AuditLog."""

    ADDITIONAL = "AdditionalUsers"
    AUDIT = "AuditLog"
    PARTITION = "additional"

    def __init__(self, connection_string: str):
        from azure.data.tables import TableServiceClient

        service = TableServiceClient.from_connection_string(connection_string)
        self.additional = service.create_table_if_not_exists(self.ADDITIONAL)
        self.audit = service.create_table_if_not_exists(self.AUDIT)

    def list_additional(self) -> list[AdditionalUser]:
        rows = self.additional.query_entities(f"PartitionKey eq '{self.PARTITION}'")
        return [AdditionalUser.from_dict({**r, "id": r["RowKey"]}) for r in rows]

    def get_additional(self, entry_id: str) -> AdditionalUser | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            r = self.additional.get_entity(self.PARTITION, entry_id)
        except ResourceNotFoundError:
            return None
        return AdditionalUser.from_dict({**r, "id": r["RowKey"]})

    def save_additional(self, entry: AdditionalUser) -> None:
        body = {k: v for k, v in asdict(entry).items() if k != "id"}
        self.additional.upsert_entity({"PartitionKey": self.PARTITION, "RowKey": entry.id, **body})

    def delete_additional(self, entry_id: str) -> None:
        self.additional.delete_entity(self.PARTITION, entry_id)

    def add_audit(self, event: AuditEvent) -> None:
        # Inverted timestamp in the RowKey so the newest events sort first.
        inverted = f"{10**13 - int(datetime.now(timezone.utc).timestamp() * 1000):013d}"
        self.audit.create_entity({"PartitionKey": "audit", "RowKey": f"{inverted}-{new_id()[:8]}", **asdict(event)})

    def list_audit(self, limit: int = 500) -> list[AuditEvent]:
        out = []
        for r in self.audit.query_entities("PartitionKey eq 'audit'", results_per_page=limit):
            out.append(AuditEvent(**{k: r.get(k, "") for k in ("at", "actor", "action", "identifier", "details")}))
            if len(out) >= limit:
                break
        return out


def make_store(cfg):
    if cfg.store_backend == "table":
        if not cfg.storage_connection_string:
            raise RuntimeError("STORE_BACKEND=table needs STORAGE_CONNECTION_STRING")
        return TableStore(cfg.storage_connection_string)
    return FileStore(cfg.store_file)
