"""RAG retrieval for augmenting prompts with relevant context."""

import structlog

from realtorai.rag.config import get_top_k
from realtorai.rag.store import get_vector_store

logger = structlog.get_logger()

# Source-kind filters for tool-driven retrieval. "legal" = statute/rules/
# ethics PDFs; "templates" = the team's email templates; "policies" = the
# office P&P manual.
KNOWLEDGE_KINDS: dict[str, list[str]] = {
    "legal": [
        "maine_title32_ch114.pdf",
        "maine_re_commission_rules_2025-10.pdf",
        "nar_code_of_ethics_2026.pdf",
    ],
    "templates": ["email_templates.md"],
    "policies": ["policies_and_procedures.md"],
}


def search_knowledge(query: str, kind: str | None = None, n_results: int = 4) -> str:
    """Tool-facing knowledge-base search with source-kind filtering.

    Returns a formatted string with [source section] citations per hit —
    the section-aware chunks carry their statute/rule headers, so answers
    can cite "§13271" instead of hallucinating a reference.
    """
    store = get_vector_store()
    where = None
    sources = KNOWLEDGE_KINDS.get(kind or "")
    if sources:
        where = {"source": {"$in": sources}}
    results = store.query(query, n_results=n_results, where=where)
    if not results:
        return "No knowledge-base matches."
    lines = []
    for r in results:
        meta = r.get("metadata", {})
        cite = meta.get("source", "?")
        if meta.get("section"):
            cite += f" — {meta['section']}"
        text = " ".join((r.get("text") or "").split())
        lines.append(f"[{cite}] {text[:600]}")
    return "\n---\n".join(lines)


class RAGRetriever:
    """Retrieves relevant context from the knowledge base.

    Used to augment prompts with domain-specific information
    before sending to the LLM.
    """

    def __init__(self):
        self.store = get_vector_store()
        self.top_k = get_top_k()

    def retrieve(
        self,
        query: str,
        n_results: int | None = None,
        source_filter: str | None = None,
    ) -> list[dict]:
        """Retrieve relevant documents for a query.

        Args:
            query: The query text
            n_results: Number of results (defaults to config top_k)
            source_filter: Optional filter by source

        Returns:
            List of results with text, metadata, and distance
        """
        n = n_results or self.top_k

        where = None
        if source_filter:
            where = {"source": source_filter}

        results = self.store.query(query, n_results=n, where=where)

        logger.debug(
            "rag_retrieved",
            query=query[:50],
            results=len(results),
        )

        return results

    def get_context(
        self,
        query: str,
        n_results: int | None = None,
        max_chars: int = 3000,
    ) -> str:
        """Get formatted context string for prompt augmentation.

        Args:
            query: The query text
            n_results: Number of results
            max_chars: Maximum characters in context

        Returns:
            Formatted context string, or empty string if no results
        """
        results = self.retrieve(query, n_results)

        if not results:
            return ""

        # Build context string
        context_parts = []
        total_chars = 0

        for i, result in enumerate(results, 1):
            text = result["text"]
            source = result.get("metadata", {}).get("source", "unknown")

            # Truncate if we're near the limit
            remaining = max_chars - total_chars
            if remaining < 100:
                break

            if len(text) > remaining:
                text = text[:remaining] + "..."

            context_parts.append(f"[{i}] ({source})\n{text}")
            total_chars += len(text) + 50  # Account for formatting

        if not context_parts:
            return ""

        context = "\n\n".join(context_parts)

        logger.debug(
            "context_generated",
            query=query[:50],
            chunks=len(context_parts),
            chars=len(context),
        )

        return context

    def augment_prompt(
        self,
        prompt: str,
        n_results: int | None = None,
    ) -> str:
        """Augment a prompt with relevant context.

        Args:
            prompt: The original prompt
            n_results: Number of context chunks to include

        Returns:
            Augmented prompt with context prepended
        """
        context = self.get_context(prompt, n_results)

        if not context:
            return prompt

        augmented = f"""Relevant information from the knowledge base:

{context}

---

{prompt}"""

        return augmented


# Global instance
_retriever: RAGRetriever | None = None


def get_retriever() -> RAGRetriever:
    """Get the global RAG retriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = RAGRetriever()
    return _retriever


def retrieve_context(query: str, n_results: int | None = None) -> str:
    """Convenience function to retrieve context for a query."""
    return get_retriever().get_context(query, n_results)


def augment_with_rag(prompt: str, n_results: int | None = None) -> str:
    """Convenience function to augment a prompt with RAG context."""
    return get_retriever().augment_prompt(prompt, n_results)
