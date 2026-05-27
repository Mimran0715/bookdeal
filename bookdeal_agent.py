from __future__ import annotations

import os
from typing import Any

from agent import (
    TinyFishClient,
    allowed_search_results,
    build_search_queries,
    dedupe_candidates,
    domains_for_location,
    extract_from_fetched_pages,
    extract_from_search_results,
    load_env,
)
from rank import BookCandidate, choose_best


class BookDealAgentError(RuntimeError):
    pass


def run_bookdeal_agent(
    book: str,
    *,
    location: str = "US",
    language: str = "en",
    max_results: int = 8,
    search_groups: int = 3,
    model: str | None = None,
    enable_logfire: bool = False,
) -> dict[str, Any]:
    try:
        from pydantic import BaseModel, Field
        from pydantic_ai import Agent
        from pydantic_ai.usage import UsageLimits
    except ImportError as exc:
        raise BookDealAgentError(
            "Install agent dependencies first: pip install 'pydantic-ai[logfire]'"
        ) from exc

    load_env()
    if enable_logfire or os.environ.get("BOOKDEAL_LOGFIRE") == "1":
        _configure_logfire()

    class DealLink(BaseModel):
        merchant: str
        url: str
        total: str
        format: str = Field(default="print", description="Either print or ebook.")
        condition: str
        reason: str = Field(default="", description="Short reason this link is useful.")

    class DealDecision(BaseModel):
        book: str
        best: DealLink | None
        backups: list[DealLink] = Field(default_factory=list)
        summary: str
        attempts: list[str] = Field(default_factory=list)

    client = TinyFishClient()
    model_name = model or os.environ.get("BOOKDEAL_MODEL", "google-gla:gemini-2.5-flash")
    agent = Agent(
        model_name,
        output_type=DealDecision,
        instructions=(
            "You are BookDealAgent. Your goal is to find the cheapest good book or ebook deal. "
            "Use the tools instead of guessing. Start with retailer_search, then fetch_and_extract "
            "for promising URLs, then rank_candidates. If no candidates are found, retry with more "
            "retailer groups or the other supported location when that is reasonable. Include print "
            "books and ebooks, but avoid audiobooks, summaries, study guides, rentals, or suspicious listings. "
            "Return a minimal answer focused on links and label each deal as print or ebook."
        ),
    )

    @agent.tool_plain
    def retailer_search(
        query_book: str,
        search_location: str = location,
        groups_to_try: int = search_groups,
        max_urls: int = max_results,
    ) -> dict[str, Any]:
        """Search only known book-retailer domains and return fetchable retailer URLs."""
        domains = domains_for_location(search_location)
        results = []
        queries = build_search_queries(query_book, domains)[: max(1, min(groups_to_try, 5))]
        for query in queries:
            results.extend(client.search(query, location=search_location, language=language))
            if len(allowed_search_results(results, domains)) >= max_urls:
                break

        allowed = allowed_search_results(results, domains)[: max(1, min(max_urls, 10))]
        candidates = extract_from_search_results(query_book, allowed)
        return {
            "location": search_location,
            "queries": queries,
            "urls": [result.url for result in allowed],
            "snippet_candidates": [_candidate_dict(candidate) for candidate in candidates],
        }

    @agent.tool_plain
    def fetch_and_extract(query_book: str, urls: list[str]) -> dict[str, Any]:
        """Fetch retailer pages and extract price candidates from rendered page content."""
        pages = client.fetch(urls[:10])
        candidates = extract_from_fetched_pages(query_book, pages)
        return {
            "fetched_pages": len(pages),
            "candidates": [_candidate_dict(candidate) for candidate in dedupe_candidates(candidates)],
        }

    @agent.tool_plain
    def rank_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Rank extracted book candidates and return the best deal plus backups."""
        hydrated = [_candidate_from_dict(candidate) for candidate in candidates]
        best, backups = choose_best(hydrated)
        return {
            "best": _candidate_dict(best) if best else None,
            "backups": [_candidate_dict(candidate) for candidate in backups],
            "candidate_count": len(hydrated),
            "filtered_count": len([candidate for candidate in hydrated if candidate.flags]),
        }

    prompt = (
        f"Find the cheapest good book or ebook deal for: {book!r}. "
        f"Preferred location: {location}. Inspect up to {max_results} retailer URLs. "
        "If snippets have candidates, include them with fetched candidates before ranking."
    )
    result = agent.run_sync(
        prompt,
        usage_limits=UsageLimits(request_limit=6, tool_calls_limit=8),
    )
    return result.output.model_dump()


def _candidate_dict(candidate: BookCandidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "title": candidate.title,
        "merchant": candidate.merchant,
        "url": candidate.url,
        "price": candidate.price,
        "currency": candidate.currency,
        "shipping": candidate.shipping,
        "total": candidate.total,
        "display_total": candidate.display_total,
        "format": candidate.format,
        "condition": candidate.condition,
        "source": candidate.source,
        "evidence": candidate.evidence,
        "trust": candidate.trust,
        "flags": list(candidate.flags),
        "score": candidate.score,
    }


def _candidate_from_dict(data: dict[str, Any]) -> BookCandidate:
    condition = str(data.get("condition") or "unknown")
    if str(data.get("format") or "").lower() == "ebook":
        condition = "ebook"
    return BookCandidate(
        title=str(data.get("title") or ""),
        merchant=str(data.get("merchant") or "unknown"),
        url=str(data.get("url") or ""),
        price=float(data.get("price") or 0),
        currency=str(data.get("currency") or "$"),
        shipping=_optional_float(data.get("shipping")),
        condition=condition,
        source=str(data.get("source") or "agent"),
        evidence=str(data.get("evidence") or ""),
        trust=float(data.get("trust") or 0.5),
        flags=tuple(data.get("flags") or ()),
    )


def _configure_logfire() -> None:
    try:
        import logfire

        logfire.configure()
        logfire.instrument_pydantic_ai()
    except Exception as exc:
        raise BookDealAgentError(f"Logfire setup failed: {exc}") from exc


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
