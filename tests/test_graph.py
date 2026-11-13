from uar.graph import GraphClient, parse_user


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, pages, fail_signin=False):
        self.pages, self.fail_signin, self.selects = pages, fail_signin, []

    def post(self, url, data=None, timeout=None):
        return Resp(200, {"access_token": "t"})

    def get(self, url, params=None, headers=None, timeout=None):
        if params is not None:
            self.selects.append(params["$select"])
            if self.fail_signin and "signInActivity" in params["$select"]:
                return Resp(403, {"error": {"code": "Authorization_RequestDenied", "message": "Insufficient privileges"}})
            return Resp(200, {"value": self.pages[0], "@odata.nextLink": "next" if len(self.pages) > 1 else None})
        return Resp(200, {"value": self.pages[1]})


def test_parse_user_keys_and_last_sign_in():
    u = parse_user({"id": "1", "userPrincipalName": "A@X.com", "mail": "a.b@x.com", "proxyAddresses": ["SMTP:A.B@x.com", "x500:/o=x",
                    "smtp:alias@x.com"], "otherMails": ["home@y.com"], "accountEnabled": True,
                    "signInActivity": {"lastSignInDateTime": "2026-10-01T10:00:00Z", "lastNonInteractiveSignInDateTime": "2026-11-01T10:00:00Z"},
                    "assignedLicenses": [{"skuId": "s"}]})
    assert u.keys == {"a@x.com", "a.b@x.com", "alias@x.com", "home@y.com"}
    assert u.last_sign_in == "2026-11-01" and u.licensed


def test_paging():
    session = FakeSession([[{"id": "1", "accountEnabled": True}], [{"id": "2", "accountEnabled": False}]])
    users = GraphClient("t", "c", "s", "off", session=session).list_users()
    assert [u.id for u in users] == ["1", "2"]
    assert "signInActivity" not in session.selects[0]


def test_signin_activity_falls_back_when_not_permitted():
    session = FakeSession([[{"id": "1", "accountEnabled": True}]], fail_signin=True)
    client = GraphClient("t", "c", "s", "auto", session=session)
    assert [u.id for u in client.list_users()] == ["1"]
    assert client.notes and "AuditLog.Read.All" in client.notes[0]
