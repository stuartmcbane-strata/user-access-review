import pytest

from uar import Sources, create_app
from uar.config import Config
from uar.graph import parse_user
from uar.hibob import parse_person
from uar.store import FileStore

HIBOB = [
    {"id": "1", "email": "alice@strata.com", "displayName": "Alice A", "internal": {"status": "Active", "lifecycleStatus": "Employed"}},
    {"id": "2", "email": "bob@strata.com", "displayName": "Bob B", "internal": {"status": "Active", "lifecycleStatus": "Employed"}},
    {"id": "3", "email": "carol@strata.com", "displayName": "Carol C",
     "internal": {"status": "Inactive", "lifecycleStatus": "Terminated", "terminationDate": "2026-01-31"}},
    {"id": "4", "email": "dan@strata.com", "displayName": "Dan D", "internal": {"status": "Inactive", "lifecycleStatus": "Hired"},
     "work": {"startDate": "2026-12-01"}},
    {"id": "5", "email": "erin@strata.com", "displayName": "Erin E", "internal": {"status": "Active", "lifecycleStatus": "Employed"}},
]

GRAPH = [
    {"id": "a", "displayName": "Alice A", "userPrincipalName": "alice@strata.com", "mail": "alice@strata.com", "accountEnabled": True,
     "userType": "Member"},
    {"id": "b", "displayName": "Bob B", "userPrincipalName": "bob.b@strata.onmicrosoft.com", "accountEnabled": True,
     "userType": "Member", "proxyAddresses": ["SMTP:Bob@strata.com", "smtp:bobby@strata.com"]},
    {"id": "c", "displayName": "Carol C", "userPrincipalName": "carol@strata.com", "accountEnabled": True, "userType": "Member"},
    {"id": "d", "displayName": "Dan D", "userPrincipalName": "dan@strata.com", "accountEnabled": True, "userType": "Member"},
    {"id": "e", "displayName": "Erin E", "userPrincipalName": "erin@strata.com", "accountEnabled": False, "userType": "Member"},
    {"id": "g", "displayName": "Gus Guest", "userPrincipalName": "gus_partner.com#EXT#@strata.onmicrosoft.com",
     "mail": "gus@partner.com", "accountEnabled": True, "userType": "Guest"},
    {"id": "s", "displayName": "Scanner", "userPrincipalName": "scanner@strata.com", "accountEnabled": True, "userType": "Member"},
    {"id": "x", "displayName": "Old Contractor", "userPrincipalName": "old@strata.com", "accountEnabled": False, "userType": "Member"},
]


class FakeSource:
    def __init__(self, rows, parse):
        self.rows, self.parse, self.calls, self.notes = rows, parse, 0, []

    def list_people(self):
        self.calls += 1
        return [self.parse(r) for r in self.rows]

    list_users = list_people


@pytest.fixture
def people():
    return [parse_person(r) for r in HIBOB]


@pytest.fixture
def ms_users():
    return [parse_user(r) for r in GRAPH]


@pytest.fixture
def store(tmp_path):
    return FileStore(str(tmp_path / "store.json"))


@pytest.fixture
def make_client(store, monkeypatch):
    def factory(**cfg_overrides):
        monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
        cfg = Config(**{"auth_mode": "easyauth", **cfg_overrides})
        sources = Sources(cfg, FakeSource(HIBOB, parse_person), FakeSource(GRAPH, parse_user), store)
        app = create_app(cfg, sources=sources, store=store)
        app.config["TESTING"] = True
        return app.test_client()

    return factory


AUTH = {"X-MS-CLIENT-PRINCIPAL-NAME": "Reviewer@Strata.com", "Origin": "http://localhost"}
