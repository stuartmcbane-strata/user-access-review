from datetime import date

from uar.compare import compare
from uar.store import AdditionalUser


def names(rows):
    return sorted(r.user.id for r in rows)


def test_classification(people, ms_users):
    review = compare(ms_users, people, [])
    assert names(review.matched) == ["a", "b", "d"]  # b via proxy address, d is a pre-start joiner
    assert names(review.leavers) == ["c"]
    assert names(review.unmatched) == ["g", "s"]
    assert [r.person.email for r in review.no_login] == ["erin@strata.com"]
    assert "blocked" in review.no_login[0].note
    assert review.microsoft_enabled == 6 and review.microsoft_disabled == 2
    assert review.hibob_valid == 4 and review.hibob_leavers == 1


def test_prehires_can_be_excluded(people, ms_users):
    review = compare(ms_users, people, [], include_prehires=False)
    assert "d" in names(review.leavers)


def test_guests_can_be_excluded(people, ms_users):
    review = compare(ms_users, people, [], include_guests=False)
    assert names(review.unmatched) == ["s"]


def test_additional_entries_cover_by_identifier_or_object_id(people, ms_users):
    entries = [
        AdditionalUser(id="1", identifier="gus@partner.com", category="External / guest", reason="Auditor"),
        AdditionalUser(id="2", identifier="renamed@strata.com", ms_object_id="s", category="Service account", reason="Scanner"),
        AdditionalUser(id="3", identifier="old@strata.com", category="Contractor", reason="Gone"),
        AdditionalUser(id="4", identifier="nobody@x.com", category="Other", reason="Typo"),
    ]
    review = compare(ms_users, people, entries)
    assert names(review.covered) == ["g", "s"]
    assert review.unmatched == []
    stale = {r.entry.identifier: r.note for r in review.stale}
    assert "disabled" in stale["old@strata.com"]
    assert "No Microsoft account" in stale["nobody@x.com"]


def test_expired_entry_no_longer_covers(people, ms_users):
    entries = [AdditionalUser(id="1", identifier="scanner@strata.com", category="Service account", reason="x", expires="2026-01-01")]
    review = compare(ms_users, people, entries, today=date(2026, 6, 1))
    row = next(r for r in review.unmatched if r.user.id == "s")
    assert "expired 2026-01-01" in row.note
    assert review.stale == []


def test_additional_entry_overrides_leaver(people, ms_users):
    entries = [AdditionalUser(id="1", identifier="carol@strata.com", category="Contractor", reason="Rehired as contractor")]
    review = compare(ms_users, people, entries)
    assert names(review.covered) == ["c"] and review.leavers == []
    assert "HiBob leaver" in review.covered[0].note
