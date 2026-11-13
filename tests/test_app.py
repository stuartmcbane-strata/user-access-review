import base64
import json

from conftest import AUTH


def test_requires_easy_auth_identity(make_client):
    client = make_client()
    resp = client.get("/")
    assert resp.status_code == 401
    assert b"Sign in with Microsoft" in resp.data
    assert client.get("/healthz").status_code == 200


def test_refuses_when_app_service_auth_disabled(make_client, monkeypatch):
    client = make_client()
    monkeypatch.setenv("WEBSITE_SITE_NAME", "strata-user-access-review")
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "False")
    assert client.get("/", headers=AUTH).status_code == 500


def test_allowed_users(make_client):
    client = make_client(allowed_users=["boss@strata.com"])
    assert client.get("/", headers=AUTH).status_code == 403
    assert client.get("/", headers={"X-MS-CLIENT-PRINCIPAL-NAME": "Boss@strata.com"}).status_code == 200


def test_display_name_from_principal_claims(make_client):
    claims = {"claims": [{"typ": "name", "val": "Rita Reviewer"}]}
    header = base64.b64encode(json.dumps(claims).encode()).decode()
    resp = make_client().get("/", headers={**AUTH, "X-MS-CLIENT-PRINCIPAL": header})
    assert b"Rita Reviewer" in resp.data


def test_review_page(make_client):
    resp = make_client().get("/", headers=AUTH)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "scanner@strata.com" in body and "Mark as additional" in body
    assert "Content-Security-Policy" in resp.headers


def test_post_requires_same_origin(make_client):
    client = make_client()
    form = {"identifier": "scanner@strata.com", "category": "Service account", "reason": "Printer scan-to-email"}
    assert client.post("/additional", data=form, headers={"X-MS-CLIENT-PRINCIPAL-NAME": "r@strata.com"}).status_code == 403
    assert client.post("/additional", data=form, headers={**AUTH, "Origin": "https://evil.example"}).status_code == 403


def test_add_edit_delete_with_audit(make_client, store):
    client = make_client()
    form = {"identifier": "Scanner@Strata.com", "category": "Service account", "reason": "Printer scan-to-email",
            "next": "/#unmatched"}
    resp = client.post("/additional", data=form, headers=AUTH)
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/#unmatched")
    [entry] = store.list_additional()
    assert entry.identifier == "scanner@strata.com" and entry.added_by == "reviewer@strata.com"

    page = client.get("/", headers=AUTH).data.decode()
    assert page.count("scanner@strata.com") >= 1

    dup = client.post("/additional", data=form, headers=AUTH, follow_redirects=True)
    assert b"already on the additional users list" in dup.data
    assert len(store.list_additional()) == 1

    resp = client.post(f"/additional/{entry.id}", data={**form, "expires": "2027-01-31", "sponsor": "IT"}, headers=AUTH)
    assert resp.status_code == 302
    assert store.get_additional(entry.id).expires == "2027-01-31"

    assert client.post(f"/additional/{entry.id}/delete", data={"next": "//evil.example"}, headers=AUTH).headers[
        "Location"] == "/additional"
    assert store.list_additional() == []
    actions = [e.action for e in store.list_audit()]
    assert sorted(actions) == ["add", "delete", "edit"]
    assert "2027-01-31" in next(e.details for e in store.list_audit() if e.action == "edit")


def test_validation(make_client, store):
    client = make_client()
    for form in ({"identifier": "not-an-email", "category": "Other", "reason": "x"},
                 {"identifier": "a@b.com", "category": "Bogus", "reason": "x"},
                 {"identifier": "a@b.com", "category": "Other", "reason": ""},
                 {"identifier": "a@b.com", "category": "Other", "reason": "x", "expires": "31/01/2027"}):
        client.post("/additional", data=form, headers=AUTH)
    assert store.list_additional() == []


def test_csv_import_and_export(make_client, store):
    import io

    client = make_client()
    csv_text = "email,display_name,category,reason,expires\nscanner@strata.com,Scanner,Service account,Printer,\n" \
               "gus@partner.com,Gus,External / guest,Auditor,2099-01-01\nbad,,,,\n"
    resp = client.post("/additional/import", data={"file": (io.BytesIO(csv_text.encode()), "x.csv")}, headers=AUTH,
                       content_type="multipart/form-data", follow_redirects=True)
    assert b"Imported 2 entries" in resp.data
    assert len(store.list_additional()) == 2

    client.post("/refresh", headers=AUTH)
    csv_out = client.get("/export/covered.csv", headers=AUTH).data.decode()
    assert "scanner@strata.com" in csv_out and "gus_partner.com#ext#" in csv_out
    assert "scanner@strata.com" not in client.get("/export/unmatched.csv", headers=AUTH).data.decode()
    assert client.get("/export/nope.csv", headers=AUTH).status_code == 404


def test_csv_formula_injection_is_neutralised():
    from uar import _csv_safe

    assert _csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _csv_safe("normal") == "normal"


def test_source_error_is_shown(make_client):
    client = make_client()
    sources = client.application.config["UAR_SOURCES"]

    def boom():
        raise RuntimeError("Microsoft Graph /users returned HTTP 403")

    sources.microsoft.list_users = boom
    sources.invalidate()
    resp = client.get("/", headers=AUTH)
    assert resp.status_code == 200 and b"HTTP 403" in resp.data


def test_cache(make_client):
    client = make_client()
    sources = client.application.config["UAR_SOURCES"]
    client.get("/", headers=AUTH)
    client.get("/", headers=AUTH)
    assert sources.hibob.calls == 1
    client.post("/refresh", headers=AUTH)
    client.get("/", headers=AUTH)
    assert sources.hibob.calls == 2
