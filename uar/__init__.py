import csv
import io
import json
import logging
import threading
import time
from dataclasses import asdict
from datetime import date, datetime, timezone

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, url_for

from .auth import AuthError, current_principal, same_origin
from .compare import Review, compare
from .config import Config
from .graph import FileMicrosoftSource, GraphClient
from .hibob import HiBobClient
from .store import CATEGORIES, AdditionalUser, AuditEvent, make_store, new_id, now_iso

log = logging.getLogger(__name__)

SECTIONS = {
    "unmatched": "Microsoft not in HiBob",
    "leavers": "HiBob leavers who can sign in",
    "no_login": "HiBob staff with no Microsoft login",
    "covered": "Covered by additional users",
    "matched": "Matched to HiBob",
    "stale": "Stale additional entries",
}


class Sources:
    """Pulls both systems and caches the comparison for CACHE_MINUTES."""

    def __init__(self, cfg: Config, hibob, microsoft, store):
        self.cfg, self.hibob, self.microsoft, self.store = cfg, hibob, microsoft, store
        self._lock = threading.Lock()
        self._cached: tuple[float, list, list] | None = None
        self.notes: list[str] = []
        self.refreshed_at = ""

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def review(self) -> Review:
        with self._lock:
            if self._cached is None or time.time() - self._cached[0] > self.cfg.cache_minutes * 60:
                people = self.hibob.list_people()
                users = self.microsoft.list_users()
                self.notes = list(getattr(self.microsoft, "notes", []))
                self._cached = (time.time(), people, users)
                self.refreshed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            _, people, users = self._cached
        return compare(
            users,
            people,
            self.store.list_additional(),
            include_prehires=self.cfg.hibob_include_prehires,
            include_guests=self.cfg.microsoft_include_guests,
        )


def build_sources(cfg: Config, store) -> Sources:
    hibob = HiBobClient(cfg.hibob_base_url, cfg.hibob_service_user_id, cfg.hibob_service_user_token)
    if cfg.microsoft_users_file:
        microsoft = FileMicrosoftSource(cfg.microsoft_users_file)
    else:
        microsoft = GraphClient(cfg.graph_tenant_id, cfg.graph_client_id, cfg.graph_client_secret, cfg.graph_signin_activity)
    return Sources(cfg, hibob, microsoft, store)


def section_rows(review: Review, section: str) -> tuple[list[str], list[list[str]]]:
    if section in ("unmatched", "leavers", "covered", "matched"):
        header = ["Display name", "UPN", "Mail", "Type", "Licensed", "Created", "Last sign-in", "HiBob", "Additional entry",
                  "Note"]
        rows = []
        for r in getattr(review, section):
            u = r.user
            hb = f"{r.hibob.display_name} ({r.hibob.status}/{r.hibob.lifecycle})" if r.hibob else ""
            add = f"{r.additional.category}: {r.additional.reason}" if r.additional else ""
            rows.append([u.display_name, u.upn, u.mail, u.user_type, "Yes" if u.licensed else "No", u.created,
                         u.last_sign_in, hb, add, r.note])
        return header, rows
    if section == "no_login":
        header = ["Display name", "Email", "Status", "Lifecycle", "Start date", "Title", "Department", "Site", "Note"]
        return header, [[r.person.display_name, r.person.email, r.person.status, r.person.lifecycle, r.person.start_date,
                         r.person.title, r.person.department, r.person.site, r.note] for r in review.no_login]
    if section == "stale":
        header = ["Identifier", "Display name", "Category", "Reason", "Sponsor", "Expires", "Added by", "Note"]
        return header, [[r.entry.identifier, r.entry.display_name, r.entry.category, r.entry.reason, r.entry.sponsor,
                         r.entry.expires, r.entry.added_by, r.note] for r in review.stale]
    abort(404)


def _clean(value: str | None, limit: int = 300) -> str:
    return (value or "").strip()[:limit]


def create_app(cfg: Config | None = None, sources: Sources | None = None, store=None) -> Flask:
    cfg = cfg or Config.from_env()
    store = store or make_store(cfg)
    sources = sources or build_sources(cfg, store)
    app = Flask(__name__)
    app.secret_key = new_id()  # flash messages only; nothing security-relevant lives in the Flask session
    app.config.update(UAR_CONFIG=cfg, UAR_STORE=store, UAR_SOURCES=sources)

    @app.errorhandler(AuthError)
    def _auth_error(exc: AuthError):
        return render_template("error.html", title="Access denied", message=exc.message, login=exc.status == 401), exc.status

    @app.before_request
    def _authenticate():
        if request.path == "/healthz":
            return None
        g.user = current_principal(request, cfg)
        if request.method == "POST" and not same_origin(request):
            abort(403, "Cross-site form post rejected.")
        return None

    @app.after_request
    def _headers(resp: Response):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'",
        )
        return resp

    @app.context_processor
    def _globals():
        return {"user": getattr(g, "user", None), "sections": SECTIONS, "categories": CATEGORIES}

    def audit(action: str, identifier: str, details: dict | None = None) -> None:
        store.add_audit(AuditEvent(at=now_iso(), actor=g.user.name, action=action, identifier=identifier,
                                   details=json.dumps(details or {}, sort_keys=True)))

    def load_review():
        try:
            return sources.review(), None
        except Exception as exc:  # shown on the page so the reviewer can see which system failed
            log.exception("refresh failed")
            return None, str(exc)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def index():
        review, error = load_review()
        return render_template("index.html", review=review, error=error, notes=sources.notes,
                               refreshed_at=sources.refreshed_at, cfg=cfg)

    @app.post("/refresh")
    def refresh():
        sources.invalidate()
        return redirect(url_for("index"))

    @app.get("/export/<section>.csv")
    def export(section: str):
        if section not in SECTIONS:
            abort(404)
        review, error = load_review()
        if review is None:
            abort(502, error)
        header, rows = section_rows(review, section)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        for row in rows:
            writer.writerow([_csv_safe(v) for v in row])
        name = f"user-access-review-{section}-{date.today().isoformat()}.csv"
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/additional")
    def additional_list():
        entries = sorted(store.list_additional(), key=lambda e: e.identifier.lower())
        prefill = {k: _clean(request.args.get(k)) for k in ("identifier", "display_name", "ms_object_id", "category", "next")}
        return render_template("additional.html", entries=entries, prefill=prefill, today=date.today())

    def form_entry(existing: AdditionalUser | None) -> tuple[AdditionalUser | None, str]:
        f = request.form
        identifier = _clean(f.get("identifier"), 256).lower()
        if "@" not in identifier or " " in identifier:
            return None, "Enter the user's sign-in name / email (UPN), e.g. jo.bloggs@partner.com."
        category = _clean(f.get("category"), 50)
        if category not in CATEGORIES:
            return None, "Choose a category."
        reason = _clean(f.get("reason"), 500)
        if not reason:
            return None, "Give a reason this account needs access."
        expires = _clean(f.get("expires"), 10)
        if expires:
            try:
                date.fromisoformat(expires)
            except ValueError:
                return None, "Expiry must be a date (YYYY-MM-DD)."
        for other in store.list_additional():
            if other.identifier.lower() == identifier and (existing is None or other.id != existing.id):
                return None, f"{identifier} is already on the additional users list."
        entry = existing or AdditionalUser(id=new_id(), identifier=identifier, added_by=g.user.name, added_at=now_iso())
        entry.identifier = identifier
        entry.display_name = _clean(f.get("display_name"), 200)
        entry.category = category
        entry.reason = reason
        entry.sponsor = _clean(f.get("sponsor"), 200)
        entry.expires = expires
        entry.ms_object_id = _clean(f.get("ms_object_id"), 64) or (existing.ms_object_id if existing else "")
        if existing:
            entry.updated_by, entry.updated_at = g.user.name, now_iso()
        return entry, ""

    @app.post("/additional")
    def additional_create():
        entry, problem = form_entry(None)
        if problem:
            flash(problem, "error")
            return redirect(url_for("additional_list", **{k: request.form.get(k, "") for k in
                                                          ("identifier", "display_name", "ms_object_id", "category", "next")}))
        store.save_additional(entry)
        audit("add", entry.identifier, _audit_fields(entry))
        flash(f"Added {entry.identifier}.", "ok")
        return redirect(_safe_next(request.form.get("next")) or url_for("additional_list"))

    @app.get("/additional/<entry_id>/edit")
    def additional_edit(entry_id: str):
        entry = store.get_additional(entry_id) or abort(404)
        return render_template("edit.html", entry=entry)

    @app.post("/additional/<entry_id>")
    def additional_update(entry_id: str):
        existing = store.get_additional(entry_id) or abort(404)
        before = _audit_fields(existing)
        entry, problem = form_entry(AdditionalUser(**asdict(existing)))
        if problem:
            flash(problem, "error")
            return redirect(url_for("additional_edit", entry_id=entry_id))
        store.save_additional(entry)
        after = _audit_fields(entry)
        audit("edit", entry.identifier, {k: [before[k], after[k]] for k in after if before.get(k) != after[k]})
        flash(f"Updated {entry.identifier}.", "ok")
        return redirect(url_for("additional_list"))

    @app.post("/additional/<entry_id>/delete")
    def additional_delete(entry_id: str):
        entry = store.get_additional(entry_id) or abort(404)
        store.delete_additional(entry_id)
        audit("delete", entry.identifier, _audit_fields(entry))
        flash(f"Removed {entry.identifier}.", "ok")
        return redirect(_safe_next(request.form.get("next")) or url_for("additional_list"))

    @app.post("/additional/import")
    def additional_import():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            flash("Choose a CSV file to import.", "error")
            return redirect(url_for("additional_list"))
        text = upload.read().decode("utf-8-sig", errors="replace")
        added, skipped = 0, []
        existing = {e.identifier.lower() for e in store.list_additional()}
        for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
            row = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
            identifier = (row.get("identifier") or row.get("email") or row.get("upn") or "").lower()
            category = row.get("category") or "Other"
            if "@" not in identifier:
                skipped.append(f"row {i}: no email/UPN")
                continue
            if identifier in existing:
                skipped.append(f"row {i}: {identifier} already listed")
                continue
            if category not in CATEGORIES:
                category = "Other"
            expires = row.get("expires", "")
            try:
                expires and date.fromisoformat(expires)
            except ValueError:
                skipped.append(f"row {i}: bad expiry {expires!r}")
                continue
            entry = AdditionalUser(id=new_id(), identifier=identifier[:256], display_name=row.get("display_name", "")[:200],
                                   category=category, reason=(row.get("reason") or "Imported")[:500],
                                   sponsor=row.get("sponsor", "")[:200], expires=expires, added_by=g.user.name,
                                   added_at=now_iso())
            store.save_additional(entry)
            audit("import", entry.identifier, _audit_fields(entry))
            existing.add(identifier)
            added += 1
        flash(f"Imported {added} entr{'y' if added == 1 else 'ies'}." + (f" Skipped: {'; '.join(skipped[:10])}" if skipped else ""),
              "ok" if added else "error")
        return redirect(url_for("additional_list"))

    @app.get("/audit")
    def audit_log():
        return render_template("audit.html", events=store.list_audit())

    return app


def _safe_next(target: str | None) -> str:
    target = (target or "").strip()
    return target if target.startswith("/") and not target.startswith("//") and "\\" not in target else ""


def _audit_fields(e: AdditionalUser) -> dict:
    return {k: getattr(e, k) for k in ("identifier", "display_name", "category", "reason", "sponsor", "expires")}


def _csv_safe(value) -> str:
    """Stop spreadsheet formula injection when the CSV is opened in Excel."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
