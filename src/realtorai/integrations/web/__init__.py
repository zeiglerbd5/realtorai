"""Web integrations - search, scraping, etc."""

from realtorai.integrations.web.search import (
    format_search_results,
    web_search,
    web_search_news,
)

__all__ = [
    "web_search",
    "web_search_news",
    "format_search_results",
]
