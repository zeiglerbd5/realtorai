"""Retrieval plumbing — the parts that must hold without a vector store.

Retrieval *quality* needs a populated ChromaDB and a 90 MB embedding model, so
it runs weekly (see .github/workflows/evals-retrieval.yml). What can be pinned
on every push is the contract around it: that `kind` builds the right filter,
that citations render, and that `retrieve_knowledge` hands back structured hits
rather than a string. That last one is load-bearing — the eval scores by
`metadata["source"]`, and if this collapses back to a formatted string the eval
silently starts substring-matching chunk prose and passing on false hits.
"""

from typing import Any

import pytest

from realtorai.rag import retrieval
from realtorai.rag.retrieval import (
    KNOWLEDGE_KINDS,
    format_hits,
    retrieve_knowledge,
    search_knowledge,
)

HITS: list[dict[str, Any]] = [
    {
        "text": "  A disclosed dual agent   may represent both\n parties.  ",
        "metadata": {"source": "maine_title32_ch114.pdf", "section": "§13275"},
        "distance": 0.11,
    },
    {
        "text": "Licensees shall not engage in undisclosed dual agency.",
        "metadata": {"source": "nar_code_of_ethics_2026.pdf"},
        "distance": 0.29,
    },
]


class _StubStore:
    """Records the query it was handed instead of embedding anything."""

    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def query(
        self, query: str, n_results: int = 4, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append({"query": query, "n_results": n_results, "where": where})
        return self.hits


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _StubStore:
    stub = _StubStore(HITS)
    monkeypatch.setattr(retrieval, "get_vector_store", lambda: stub)
    return stub


def test_kind_filter_restricts_to_that_kinds_sources(store: _StubStore) -> None:
    retrieve_knowledge("dual agency", kind="legal")
    assert store.calls[0]["where"] == {"source": {"$in": KNOWLEDGE_KINDS["legal"]}}


def test_unknown_and_absent_kinds_do_not_filter(store: _StubStore) -> None:
    """An unrecognised kind must search everything, not silently match nothing."""
    retrieve_knowledge("dual agency", kind=None)
    retrieve_knowledge("dual agency", kind="not-a-kind")
    assert [c["where"] for c in store.calls] == [None, None]


def test_retrieve_returns_structured_hits_not_a_string(store: _StubStore) -> None:
    hits = retrieve_knowledge("dual agency", kind="legal")
    assert isinstance(hits, list)
    assert hits[0]["metadata"]["source"] == "maine_title32_ch114.pdf"


def test_citations_carry_the_section_header(store: _StubStore) -> None:
    rendered = format_hits(HITS)
    assert "[maine_title32_ch114.pdf — §13275]" in rendered
    assert "[nar_code_of_ethics_2026.pdf]" in rendered  # no section -> source alone
    assert "A disclosed dual agent may represent both parties." in rendered  # whitespace collapsed


def test_empty_results_say_so_rather_than_returning_blank() -> None:
    assert format_hits([]) == "No knowledge-base matches."


def test_search_knowledge_still_returns_the_formatted_string(store: _StubStore) -> None:
    """Two callers depend on this signature: email_agent and copilot."""
    assert search_knowledge("dual agency", kind="legal") == format_hits(HITS)
