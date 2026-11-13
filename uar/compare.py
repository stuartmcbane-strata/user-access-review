from dataclasses import dataclass, field
from datetime import date

from .graph import MicrosoftUser
from .hibob import HiBobPerson
from .store import AdditionalUser


@dataclass
class MicrosoftRow:
    user: MicrosoftUser
    hibob: HiBobPerson | None = None
    additional: AdditionalUser | None = None
    note: str = ""


@dataclass
class HiBobRow:
    person: HiBobPerson
    microsoft: MicrosoftUser | None = None
    note: str = ""


@dataclass
class AdditionalRow:
    entry: AdditionalUser
    microsoft: MicrosoftUser | None = None
    note: str = ""


@dataclass
class Review:
    unmatched: list[MicrosoftRow] = field(default_factory=list)
    leavers: list[MicrosoftRow] = field(default_factory=list)
    covered: list[MicrosoftRow] = field(default_factory=list)
    matched: list[MicrosoftRow] = field(default_factory=list)
    no_login: list[HiBobRow] = field(default_factory=list)
    stale: list[AdditionalRow] = field(default_factory=list)
    microsoft_enabled: int = 0
    microsoft_disabled: int = 0
    hibob_valid: int = 0
    hibob_leavers: int = 0


def _valid(p: HiBobPerson, include_prehires: bool) -> bool:
    return p.is_active or (include_prehires and p.is_prehire)


def _sort_ms(rows: list[MicrosoftRow]) -> list[MicrosoftRow]:
    return sorted(rows, key=lambda r: (r.user.display_name.lower(), r.user.upn))


def compare(
    microsoft: list[MicrosoftUser],
    hibob: list[HiBobPerson],
    additional: list[AdditionalUser],
    include_prehires: bool = True,
    include_guests: bool = True,
    today: date | None = None,
) -> Review:
    """Classify every sign-in-enabled Microsoft account against HiBob and the additional-users list.

    Precedence for an enabled Microsoft account: HiBob valid employee > live additional entry > HiBob leaver
    (an enabled account belonging to a terminated employee) > unmatched.
    """
    today = today or date.today()
    review = Review()

    valid_by_email: dict[str, HiBobPerson] = {}
    leaver_by_email: dict[str, HiBobPerson] = {}
    for p in hibob:
        if _valid(p, include_prehires):
            valid_by_email[p.email] = p
        elif p.email not in valid_by_email:
            leaver_by_email[p.email] = p
    for email in valid_by_email:
        leaver_by_email.pop(email, None)
    review.hibob_valid = len(valid_by_email)
    review.hibob_leavers = len(leaver_by_email)

    entries_by_key: dict[str, AdditionalUser] = {}
    entries_by_oid: dict[str, AdditionalUser] = {}
    for e in additional:
        entries_by_key.setdefault(e.identifier.strip().lower(), e)
        if e.ms_object_id:
            entries_by_oid.setdefault(e.ms_object_id, e)

    in_scope = [u for u in microsoft if include_guests or not u.is_guest]
    enabled = [u for u in in_scope if u.account_enabled]
    review.microsoft_enabled = len(enabled)
    review.microsoft_disabled = len(in_scope) - len(enabled)

    ms_by_key: dict[str, MicrosoftUser] = {}
    for u in sorted(in_scope, key=lambda u: not u.account_enabled):
        for k in sorted(u.keys):
            ms_by_key.setdefault(k, u)

    matched_entry_ids: set[str] = set()
    matched_hibob: set[str] = set()
    for u in enabled:
        person = next((valid_by_email[k] for k in sorted(u.keys) if k in valid_by_email), None)
        entry = entries_by_oid.get(u.id) or next((entries_by_key[k] for k in sorted(u.keys) if k in entries_by_key), None)
        leaver = next((leaver_by_email[k] for k in sorted(u.keys) if k in leaver_by_email), None)
        if entry:
            matched_entry_ids.add(entry.id)
        if person:
            matched_hibob.add(person.email)
            note = "Also on the additional users list" if entry else ""
            if person.is_prehire:
                note = (note + "; " if note else "") + f"Pre-start joiner (starts {person.start_date or 'n/a'})"
            review.matched.append(MicrosoftRow(u, hibob=person, additional=entry, note=note))
        elif entry and not entry.is_expired(today):
            note = f"HiBob leaver (terminated {leaver.termination_date or 'n/a'})" if leaver else ""
            review.covered.append(MicrosoftRow(u, hibob=leaver, additional=entry, note=note))
        elif leaver:
            note = f"Terminated {leaver.termination_date or 'n/a'} in HiBob"
            if entry:
                note += f"; additional entry expired {entry.expires}"
            review.leavers.append(MicrosoftRow(u, hibob=leaver, additional=entry, note=note))
        else:
            note = f"Additional entry expired {entry.expires}" if entry else ""
            review.unmatched.append(MicrosoftRow(u, additional=entry, note=note))

    for email, person in sorted(valid_by_email.items(), key=lambda kv: kv[1].display_name.lower()):
        if email in matched_hibob:
            continue
        ms = ms_by_key.get(email)
        if ms and not ms.account_enabled:
            note = "Microsoft account exists but sign-in is blocked"
        elif person.is_prehire:
            note = f"Pre-start joiner (starts {person.start_date or 'n/a'})"
        else:
            note = "No Microsoft account with this email"
        review.no_login.append(HiBobRow(person, microsoft=ms, note=note))

    for e in sorted(additional, key=lambda e: e.identifier.lower()):
        if e.id in matched_entry_ids:
            continue
        ms = (next((u for u in in_scope if u.id == e.ms_object_id), None) if e.ms_object_id else None) or ms_by_key.get(
            e.identifier.strip().lower()
        )
        if ms and not ms.account_enabled:
            note = "Microsoft account is disabled - entry can be removed"
        elif ms:
            note = "Guest account excluded from the review"
        else:
            note = "No Microsoft account matches - entry can be removed"
        review.stale.append(AdditionalRow(e, microsoft=ms, note=note))

    review.unmatched = _sort_ms(review.unmatched)
    review.leavers = _sort_ms(review.leavers)
    review.covered = _sort_ms(review.covered)
    review.matched = _sort_ms(review.matched)
    return review
