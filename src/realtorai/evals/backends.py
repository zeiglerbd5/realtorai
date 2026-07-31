"""Predictors — the things being evaluated.

The intake classifier has two real implementations and both ship: the Claude
call when a key is configured, and the keyword heuristic
(`workflows.email_trigger._heuristic_classification`) whenever it isn't. The
heuristic is not a test double — it is the production degraded path, which is
why gating CI on it is a genuine regression test rather than a stand-in for
one. Running both over the same cases also makes the gap between them
measurable instead of assumed.
"""

from __future__ import annotations

from typing import Any

from realtorai.evals.harness import Case, Prediction


async def heuristic_intake(case: Case) -> Prediction:
    """Offline keyword classifier. Deterministic, no API key, no network."""
    from realtorai.workflows.email_trigger import _heuristic_classification

    result = _heuristic_classification(
        str(case.inputs["subject"]), str(case.inputs["body"])
    )
    return Prediction(label=result.intent, detail="keyword heuristic")


async def live_intake(case: Case) -> Prediction:
    """The Claude classifier actually used in production when a key is set."""
    from realtorai.workflows.intake import classify_intake_email

    attachments = list(case.inputs.get("attachment_names") or [])
    result = await classify_intake_email(
        str(case.inputs["subject"]), str(case.inputs["body"]), attachments
    )
    return Prediction(
        label=result.intent,
        detail=f"conf={result.confidence}",
    )


INTAKE_BACKENDS: dict[str, Any] = {
    "heuristic": heuristic_intake,
    "live": live_intake,
}


async def retrieval_hit(case: Case) -> Prediction:
    """Did the expected source appear in the top-k, and at what rank?

    Scores on `metadata["source"]` rather than the rendered citation block.
    Matching against the formatted string would count a hit whenever a chunk's
    prose happened to mention the filename.
    """
    from realtorai.rag.retrieval import retrieve_knowledge

    kind = case.inputs.get("kind")
    hits = retrieve_knowledge(
        str(case.inputs["question"]),
        kind=str(kind) if kind else None,
        n_results=int(case.inputs.get("n_results", 4)),
    )
    sources = [str(h.get("metadata", {}).get("source", "")) for h in hits]
    for position, source in enumerate(sources, start=1):
        if source == case.expected:
            return Prediction(label=source, detail=f"rank {position}", rank=position)
    return Prediction(
        label=sources[0] if sources else "(no hits)",
        detail=f"top-{len(sources)}: {', '.join(sources) or 'none'}",
        rank=None,
    )


def ingested_sources() -> set[str]:
    """Source filenames currently in the vector store.

    Drives per-case `requires`: the private-corpus cases skip in CI instead of
    failing, because those documents are deliberately gitignored.
    """
    from realtorai.rag.store import get_vector_store

    store = get_vector_store()
    try:
        collection = store.collection  # type: ignore[attr-defined]
        got = collection.get(include=["metadatas"])
    except Exception:
        return set()
    metadatas = got.get("metadatas") or []
    return {str(m.get("source")) for m in metadatas if m and m.get("source")}
