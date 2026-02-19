"""Web search using DuckDuckGo.

Provides free web search capability for the model to look up
current information, market data, property details, etc.
"""

from typing import Any

import structlog
from duckduckgo_search import DDGS

logger = structlog.get_logger()


def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search the web using DuckDuckGo.

    Args:
        query: Search query string
        max_results: Maximum number of results to return

    Returns:
        List of search results with title, url, and body
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        logger.info("web_search", query=query, results=len(results))
        return results

    except Exception as e:
        logger.error("web_search_error", query=query, error=str(e))
        return []


def web_search_news(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search news articles using DuckDuckGo.

    Args:
        query: Search query string
        max_results: Maximum number of results to return

    Returns:
        List of news results with title, url, body, and date
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))

        logger.info("web_search_news", query=query, results=len(results))
        return results

    except Exception as e:
        logger.error("web_search_news_error", query=query, error=str(e))
        return []


def format_search_results(results: list[dict[str, Any]]) -> str:
    """Format search results as readable text for the model.

    Args:
        results: List of search result dicts

    Returns:
        Formatted string with all results
    """
    if not results:
        return "No results found."

    formatted = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        url = r.get("href", r.get("url", ""))
        body = r.get("body", r.get("description", ""))

        formatted.append(f"{i}. {title}\n   {url}\n   {body}")

    return "\n\n".join(formatted)
