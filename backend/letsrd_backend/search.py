"""Async search adapters for public-domain and lending-library catalogs."""

from __future__ import annotations

from typing import Any

import httpx

from .educational_pipeline import ProviderError

GUTENDEX_URL = "https://gutendex.com/books"
OPEN_LIBRARY_URL = "https://openlibrary.org/search.json"


class FreeEbookSearch:
    """Search Gutendex first and use Open Library when no results are available."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("Query parameter cannot be empty.")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50.")

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient()
        primary_error: Exception | None = None
        try:
            try:
                response = await client.get(
                    GUTENDEX_URL,
                    params={"search": query.strip()},
                    timeout=8.0,
                )
                response.raise_for_status()
                books = response.json().get("results", [])
                if books:
                    return [
                        {
                            "id": str(book.get("id", "")),
                            "title": book.get("title") or "Untitled",
                            "authors": [
                                author["name"]
                                for author in book.get("authors", [])
                                if author.get("name")
                            ],
                            "source": "Project Gutenberg (Gutendex)",
                            "formats": book.get("formats", {}),
                        }
                        for book in books[:limit]
                    ]
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
                primary_error = exc

            try:
                response = await client.get(
                    OPEN_LIBRARY_URL,
                    params={"q": query.strip(), "limit": limit},
                    timeout=8.0,
                )
                response.raise_for_status()
                docs = response.json().get("docs", [])
                results: list[dict[str, Any]] = []
                for doc in docs[:limit]:
                    key = str(doc.get("key", ""))
                    catalog_url = f"https://openlibrary.org{key}" if key.startswith("/") else ""
                    results.append(
                        {
                            "id": key.rsplit("/", 1)[-1] if key else "",
                            "title": doc.get("title") or "Untitled",
                            "authors": doc.get("author_name", []),
                            "source": "Open Library",
                            "formats": {"catalog": catalog_url} if catalog_url else {},
                        }
                    )
                return results
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
                if primary_error:
                    detail = (
                        "Both ebook indexing engines are currently unreachable: "
                        f"Gutendex: {primary_error}; Open Library: {exc}"
                    )
                else:
                    detail = f"Open Library search failed after no Gutenberg results: {exc}"
                raise ProviderError(detail) from exc
        finally:
            if owns_client:
                await client.aclose()
