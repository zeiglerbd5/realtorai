"""Web integrations - search, scraping, etc."""

from realtorai.integrations.web.search import (
    web_search,
    web_search_news,
    format_search_results,
)

__all__ = [
    "web_search",
    "web_search_news",
    "format_search_results",
]
