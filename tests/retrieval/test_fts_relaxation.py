"""Bounded FTS5 query relaxation: exact lookups unchanged, natural language recovers."""

import pytest

from orbit.database.engine import connect
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService
from orbit.retrieval.fts import FtsMessageSearch
from orbit.retrieval.service import MESSAGE_FTS_SCHEMA

MESSAGES = [
    "The nightly job failed with error ERR_PAYMENT_4471 after the gateway changed its schema.",
    "Marco owns the release notes and Priya owns the onboarding checklist.",
    "Decision meeting: avoid a hosted database and keep deployment simple.",
    "See src/orbit/retrieval/fts.py for the query builder.",
    "Café menu review: crème brûlée was too sweet.",
    "Version v1.2.3 shipped on Friday.",
    "Completely unrelated gardening note about tomatoes.",
]


@pytest.fixture()
def search(tmp_path):
    conn = connect(tmp_path / "t.db")
    repo = ChatMessageRepository(conn)
    ids = [repo.insert("p", "c", "user", m) for m in MESSAGES]
    repo.insert("other", "c", "user", "Marco owns the release notes in another project")
    fts = FtsMessageSearch(conn, MESSAGE_FTS_SCHEMA)

    def run(query, relax=True, project="p", limit=10):
        return [r.message_id for r in fts.search(query, project_id=project, limit=limit, relax=relax)], fts.last_tier

    run.ids = ids
    return run


def test_strict_matches_are_never_changed_by_relaxation(search):
    strict, tier = search("ERR_PAYMENT_4471", relax=False)
    relaxed, relaxed_tier = search("ERR_PAYMENT_4471", relax=True)
    assert strict == relaxed == [str(search.ids[0])] and tier == relaxed_tier == "strict"


def test_stopword_tier_recovers_natural_questions(search):
    assert search("who owns the release notes", relax=False)[0] == []
    found, tier = search("who owns the release notes")
    assert found == [str(search.ids[1])] and tier == "no_stopwords"


def test_or_tier_requires_most_terms_and_is_bounded(search):
    # "hosted deployment simple pizza": 3 of 4 terms present in one message.
    found, tier = search("why hosted deployment simple pizza")
    assert found == [str(search.ids[2])] and tier == "relaxed_or"
    # Only one of the terms matches: not enough, nothing is returned.
    assert search("tomatoes spaceship quantum lattice")[0] == []


def test_identifier_terms_must_still_match_in_relaxed_queries(search):
    found, tier = search("what failed with ERR_PAYMENT_9999 nightly gateway")
    assert found == []  # the identifier is required, wrong code never matches loosely
    found, _ = search("what failed with ERR_PAYMENT_4471 nightly schema gateway")
    assert found == [str(search.ids[0])]


def test_two_term_queries_are_not_relaxed(search):
    assert search("hosted pizza")[0] == []


def test_zero_result_and_empty_queries(search):
    assert search("")[0] == [] and search("   ")[0] == [] and search("!!! ???")[0] == []
    assert search("zzzz qqqq xxxx wwww")[0] == []


def test_quoted_phrase_must_be_adjacent(search):
    assert search('"release notes"', relax=False)[0] == [str(search.ids[1])]
    assert search('"notes release"', relax=False)[0] == []
    assert search('"hosted database" deployment', relax=False)[0] == [str(search.ids[2])]
    assert search('"database hosted" deployment', relax=False)[0] == []


def test_filename_and_version_lookups(search):
    assert search("src/orbit/retrieval/fts.py")[0] == [str(search.ids[3])]
    assert search("v1.2.3")[0] == [str(search.ids[5])]
    found, _ = search("which file has the query builder fts.py")
    assert found == [str(search.ids[3])]


def test_unicode_queries(search):
    assert search("café")[0] == [str(search.ids[4])]
    assert search("CRÈME brûlée")[0] == [str(search.ids[4])]


@pytest.mark.parametrize("query", ['"unbalanced', "a AND OR NOT (", "NEAR(a b)", "col:term *", "\\", "'; DROP TABLE x; --"])
def test_malformed_fts_syntax_is_treated_as_plain_text(search, query):
    assert isinstance(search(query)[0], list)  # never raises


def test_relaxation_is_project_scoped(search):
    found, _ = search("who owns the release notes", project="other")
    assert len(found) == 1 and found != [str(search.ids[1])]
    assert search("who owns the release notes", project="nobody")[0] == []


def test_service_uses_relaxation_by_default_and_can_disable_it(tmp_path):
    conn = connect(tmp_path / "s.db")
    ChatMessageRepository(conn).insert("p", "c", "user", "Marco owns the release notes")
    assert len(RetrievalService(conn).search_chat_history("p", "who owns the release notes")) == 1
    assert RetrievalService(conn, fts_relax=False).search_chat_history("p", "who owns the release notes") == []
