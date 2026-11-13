# User Access Review

Web tool that compares **everyone who can sign in to the Strata Microsoft tenant** (Entra ID users with
`accountEnabled = true`) with **valid employees in HiBob**, and lets reviewers record **additional users**
(externals, contractors, service accounts, shared mailboxes...) that legitimately have a login but aren't in HiBob.

Live at <https://strata-user-access-review.azurewebsites.net> (Entra ID sign-in required).

## What the review page shows

| Tab | Meaning |
| --- | --- |
| Microsoft not in HiBob | Sign-in enabled accounts with no valid HiBob employee and no current additional-users entry. **These are the exceptions** - disable them or mark them as additional users. |
| HiBob leavers who can sign in | Sign-in enabled accounts whose email belongs to someone HiBob shows as terminated/inactive. |
| HiBob staff with no Microsoft login | Valid HiBob employees with no sign-in enabled account (usually a different email in HiBob, or a blocked account). |
| Covered by additional users | Accounts marked off by the additional users list. |
| Matched to HiBob | Accounts matched to a valid HiBob employee. |
| Stale additional entries | Additional-users entries that no longer match an account that can sign in - safe to remove. |

Every tab can be filtered, sorted (click a column) and exported to CSV.

**Valid HiBob employee** = `internal.status = Active`, plus pre-start joiners (`lifecycleStatus = Hired`) unless
`HIBOB_INCLUDE_PREHIRES=false`. **Matching** is case-insensitive on the HiBob work email against the Microsoft
UPN, `mail`, every `smtp:` proxy address and `otherMails`. Additional-users entries match on the same keys, or on the
Microsoft object id when the entry was created from the review page (so a later UPN rename still matches).
Precedence: HiBob employee > live additional entry > HiBob leaver > exception. An entry past its expiry date no
longer counts, so the account reappears as an exception.

Additional users are stored in Azure Table Storage (`AdditionalUsers`) and every add/edit/delete/import is written to
`AuditLog` with the signed-in reviewer's UPN. Bulk import accepts a CSV with columns `identifier` (or `email`/`upn`),
`display_name`, `category`, `reason`, `sponsor`, `expires` (YYYY-MM-DD).

## Azure setup

| Resource | Name |
| --- | --- |
| Resource group | `app-integrations` (UK West) |
| App Service plan | `asp-user-access-review` (Linux B1) |
| Web app | `strata-user-access-review` (Python 3.12, gunicorn) |
| Storage account | `stuseraccessreview` (tables `AdditionalUsers`, `AuditLog`) |
| Entra app registration | `User Access Review` - used both for sign-in (App Service Authentication) and for app-only Graph reads |

App registration requirements:

* Web redirect URI `https://strata-user-access-review.azurewebsites.net/.auth/login/aad/callback`, ID tokens enabled.
* Microsoft Graph **application** permissions with admin consent: `User.Read.All` (required),
  `AuditLog.Read.All` (optional - adds last sign-in dates; needs Entra ID P1).
* Enterprise application -> Properties -> **Assignment required = Yes**; assign the reviewers. Only assigned users
  can sign in.

App Service Authentication (Easy Auth) is set to *require authentication* with the Microsoft provider, so
unauthenticated requests never reach the app. The app additionally refuses to serve if it is running on App Service
with authentication switched off (`WEBSITE_AUTH_ENABLED` not `True`), rejects cross-site form posts, and sends a
strict Content-Security-Policy.

### Deploy

```bash
zip -r app.zip app.py requirements.txt uar
az webapp deploy -g app-integrations -n strata-user-access-review --src-path app.zip --type zip
```

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `HIBOB_BASE_URL` | `https://api.hibob.com/v1` | HiBob API base URL |
| `HIBOB_SERVICE_USER_ID` / `HIBOB_SERVICE_USER_TOKEN` | | HiBob service user (needs People read incl. inactive employees and lifecycle fields) |
| `HIBOB_INCLUDE_PREHIRES` | `true` | Treat pre-start joiners as valid |
| `GRAPH_TENANT_ID` | `WEBSITE_AUTH_AAD_ALLOWED_TENANTS` | Entra tenant id |
| `GRAPH_CLIENT_ID` | | App registration (client) id |
| `GRAPH_CLIENT_SECRET` | `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET` | Client secret (defaults to the Easy Auth secret setting) |
| `GRAPH_SIGNIN_ACTIVITY` | `auto` | `auto` = read last sign-in if permitted, `on` = required, `off` = never |
| `MICROSOFT_INCLUDE_GUESTS` | `true` | Include guest (B2B) accounts in the review |
| `MICROSOFT_USERS_FILE` | | Local dev only: Graph-shaped JSON file used instead of Graph |
| `STORE_BACKEND` | `file` | `table` (Azure Table Storage) or `file` (local JSON) |
| `STORAGE_CONNECTION_STRING` | | Storage account connection string for `table` |
| `STORE_FILE` | `data/store.json` | JSON file for `file` |
| `AUTH_MODE` | `easyauth` | `easyauth` (App Service Authentication headers) or `dev` (local only) |
| `DEV_USER` | `dev.user@example.com` | Signed-in user name in `dev` mode |
| `ALLOWED_USERS` | | Optional comma-separated UPN allow-list on top of app assignment |
| `CACHE_MINUTES` | `10` | How long HiBob/Graph data is cached ("Refresh now" clears it) |

## Local development

```bash
pip install -r requirements-dev.txt
python -m pytest -q && ruff check .
AUTH_MODE=dev MICROSOFT_USERS_FILE=data/mock_microsoft_users.json HIBOB_SERVICE_USER_ID=... HIBOB_SERVICE_USER_TOKEN=... \
  gunicorn --bind 0.0.0.0:8000 app:app
```
