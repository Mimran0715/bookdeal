from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable

from rank import BookCandidate, blocked_flags, merchant_from_url, trust_for_url


SEARCH_ENDPOINT = "https://api.search.tinyfish.ai"
FETCH_ENDPOINT = "https://api.fetch.tinyfish.ai"
SEARCH_DOMAIN_GROUP_SIZE = 4

PRICE_RE = re.compile(r"(?<!\w)([$£])\s*([0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]{2})?)")
SHIPPING_RE = re.compile(
    r"(?:\+\s*)?([$£])\s*([0-9]{1,3}(?:\.[0-9]{2})?)\s*(?:shipping|delivery|ship)",
    re.IGNORECASE,
)
CONDITION_TERMS = (
    "ebook",
    "e-book",
    "kindle",
    "like new",
    "very good",
    "acceptable",
    "good",
    "used",
    "new",
)
BOOK_MARKETPLACE_TERMS = (
    "used",
    "new",
    "paperback",
    "hardcover",
    "ebook",
    "e-book",
    "kindle",
    "book",
    "shipping",
    "condition",
    "seller",
)
US_BOOK_DOMAINS = (
    "barnesandnoble.com",
    "amazon.com",
    "abebooks.com",
    "thriftbooks.com",
    "betterworldbooks.com",
    "bookshop.org",
    "booksamillion.com",
    "halfpricebooks.com",
    "target.com",
    "walmart.com",
    "powells.com",
    "biblio.com",
    "alibris.com",
    "ebay.com",
)
GB_BOOK_DOMAINS = (
    "waterstones.com",
    "blackwells.co.uk",
    "amazon.co.uk",
    "abebooks.co.uk",
    "wob.com",
    "worldofbooks.com",
    "bookshop.org",
    "ebay.co.uk",
)
SOCIAL_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "lemon8-app.com",
    "lemon8.com",
    "pinterest.com",
    "reddit.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
)
NON_BOOK_RETAIL_HOSTS = (
    "advertising.amazon.com",
    "aws.amazon.com",
    "developer.amazon.com",
    "music.amazon.com",
    "sell.amazon.com",
)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    site_name: str = ""
    position: int = 0


class TinyFishError(RuntimeError):
    pass


@dataclass
class PipelineStats:
    marketplaces_queried: int = 0
    search_groups_queried: int = 0
    search_results_returned: int = 0
    search_results_allowed: int = 0
    pages_fetch_requested: int = 0
    pages_fetched: int = 0
    candidates_extracted: int = 0
    candidates_deduped: int = 0
    listings_filtered: int = 0
    filter_reasons: dict[str, int] = field(default_factory=dict)
    final_valid_listings_ranked: int = 0
    total_seconds: float = 0.0
    timings: dict[str, float] = field(
        default_factory=lambda: {
            "search": 0.0,
            "fetch": 0.0,
            "extraction_filtering": 0.0,
            "ranking": 0.0,
            "total": 0.0,
        }
    )


@dataclass
class DealSearchResult:
    candidates: list[BookCandidate]
    stats: PipelineStats


class TinyFishClient:
    def __init__(self, api_key: str | None = None, timeout: int = 150) -> None:
        load_env()
        self.api_key = api_key or os.environ.get("TINYFISH_API_KEY")
        self.timeout = timeout
        if not self.api_key or self.api_key == "your_api_key_here":
            raise TinyFishError("Add your TinyFish API key to .env as TINYFISH_API_KEY.")

    def search(self, query: str, location: str = "US", language: str = "en", page: int = 0) -> list[SearchResult]:
        params = urllib.parse.urlencode(
            {
                "query": query,
                "location": location,
                "language": language,
                "page": page,
            }
        )
        payload = self._request("GET", f"{SEARCH_ENDPOINT}?{params}")
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
                site_name=item.get("site_name", ""),
                position=int(item.get("position") or 0),
            )
            for item in payload.get("results", [])
            if item.get("url")
        ]

    def fetch(self, urls: list[str], output_format: str = "markdown") -> list[dict[str, Any]]:
        if not urls:
            return []
        body = {
            "urls": urls[:10],
            "format": output_format,
            "links": False,
            "image_links": False,
        }
        payload = self._request("POST", FETCH_ENDPOINT, body)
        errors = payload.get("errors", [])
        for error in errors:
            url = error.get("url", "unknown URL")
            code = error.get("error", "fetch_error")
            print(f"Fetch warning: {url} failed with {code}", file=sys.stderr)
        return payload.get("results", [])

    def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "X-API-Key": self.api_key or "",
            "Accept": "application/json",
            "User-Agent": "bookdeal/0.1",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TinyFishError(f"TinyFish HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TinyFishError(f"TinyFish request failed: {exc.reason}") from exc


def find_book_deals(
    book: str,
    *,
    author: str | None = None,
    year: str | None = None,
    isbn: str | None = None,
    edition: str | None = None,
    max_results: int = 8,
    search_groups: int = 3,
    fetch_pages: bool = True,
    location: str = "US",
    language: str = "en",
    client: TinyFishClient | None = None,
) -> list[BookCandidate]:
    return find_book_deals_with_stats(
        book,
        author=author,
        year=year,
        isbn=isbn,
        edition=edition,
        max_results=max_results,
        search_groups=search_groups,
        fetch_pages=fetch_pages,
        location=location,
        language=language,
        client=client,
    ).candidates


def find_book_deals_with_stats(
    book: str,
    *,
    author: str | None = None,
    year: str | None = None,
    isbn: str | None = None,
    edition: str | None = None,
    max_results: int = 8,
    search_groups: int = 3,
    fetch_pages: bool = True,
    location: str = "US",
    language: str = "en",
    client: TinyFishClient | None = None,
    debug: bool = False,
) -> DealSearchResult:
    total_started = time.perf_counter()
    client = client or TinyFishClient()
    domains = domains_for_location(location)
    stats = PipelineStats()
    results: list[SearchResult] = []

    search_started = time.perf_counter()
    for query in build_search_queries(
        book,
        domains,
        author=author,
        year=year,
        isbn=isbn,
        edition=edition,
    )[:search_groups]:
        _debug(debug, f"search: querying retailer group {stats.search_groups_queried + 1}")
        results.extend(client.search(query, location=location, language=language))
        stats.search_groups_queried += 1
        if len(allowed_search_results(results, domains)) >= max_results:
            break
    stats.timings["search"] = _elapsed(search_started)
    stats.marketplaces_queried = min(len(domains), stats.search_groups_queried * SEARCH_DOMAIN_GROUP_SIZE)
    stats.search_results_returned = len(results)

    allowed_results = allowed_search_results(results, domains)[:max_results]
    stats.search_results_allowed = len(allowed_results)

    extraction_started = time.perf_counter()
    _debug(debug, f"extraction: scanning {len(allowed_results)} search results")
    candidates = extract_from_search_results(book, allowed_results)
    stats.candidates_extracted = len(candidates)
    stats.timings["extraction_filtering"] += _elapsed(extraction_started)

    if fetch_pages:
        # Search and fetch are free, but the free tier is rate limited. Fetch only the
        # most promising result URLs, in a single batch, so the CLI stays courteous.
        urls = [result.url for result in allowed_results]
        stats.pages_fetch_requested = len(urls)
        fetch_started = time.perf_counter()
        _debug(debug, f"fetch: fetching {len(urls)} pages")
        pages = client.fetch(urls)
        stats.timings["fetch"] = _elapsed(fetch_started)
        stats.pages_fetched = len(pages)

        extraction_started = time.perf_counter()
        _debug(debug, f"extraction: scanning {len(pages)} fetched pages")
        fetched_candidates = extract_from_fetched_pages(book, pages)
        stats.candidates_extracted += len(fetched_candidates)
        candidates.extend(fetched_candidates)
        stats.timings["extraction_filtering"] += _elapsed(extraction_started)

    dedupe_started = time.perf_counter()
    deduped = dedupe_candidates(candidates)
    stats.timings["extraction_filtering"] += _elapsed(dedupe_started)
    stats.candidates_deduped = len(deduped)
    stats.total_seconds = _elapsed(total_started)
    stats.timings["total"] = stats.total_seconds
    _debug(debug, f"pipeline: extracted {stats.candidates_extracted}, deduped to {stats.candidates_deduped}")
    return DealSearchResult(candidates=deduped, stats=stats)


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 4)


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[bookdeal debug] {message}", file=sys.stderr)


def build_search_query(
    book: str,
    domains: Iterable[str] | None = None,
    *,
    author: str | None = None,
    year: str | None = None,
    isbn: str | None = None,
    edition: str | None = None,
) -> str:
    return build_search_queries(
        book,
        domains,
        author=author,
        year=year,
        isbn=isbn,
        edition=edition,
    )[0]


def build_search_queries(
    book: str,
    domains: Iterable[str] | None = None,
    *,
    author: str | None = None,
    year: str | None = None,
    isbn: str | None = None,
    edition: str | None = None,
) -> list[str]:
    clean = " ".join(book.split())
    metadata_terms = _search_metadata_terms(author=author, year=year, isbn=isbn, edition=edition)
    blocked_terms = " ".join(
        f"-site:{domain}" for domain in (*SOCIAL_DOMAINS, *NON_BOOK_RETAIL_HOSTS)
    )
    scoped_domains = tuple(domains or US_BOOK_DOMAINS)
    queries: list[str] = []
    for group in _chunks(scoped_domains, SEARCH_DOMAIN_GROUP_SIZE):
        domain_terms = " OR ".join(f"site:{domain}" for domain in group)
        queries.append(
            f'"{clean}" {metadata_terms} '
            f"(paperback OR hardcover OR ebook OR Kindle OR used OR new) "
            f"({domain_terms}) {blocked_terms}".strip()
        )
    return queries


def _search_metadata_terms(
    *,
    author: str | None,
    year: str | None,
    isbn: str | None,
    edition: str | None,
) -> str:
    terms: list[str] = []
    if author:
        terms.append(f'"{" ".join(author.split())}"')
    if year:
        terms.append(" ".join(year.split()))
    if isbn:
        terms.append(" ".join(isbn.split()))
    if edition:
        terms.append(" ".join(edition.split()))
    return " ".join(terms)


def domains_for_location(location: str) -> tuple[str, ...]:
    normalized = location.strip().upper()
    if normalized in {"GB", "UK", "UNITED KINGDOM"}:
        return GB_BOOK_DOMAINS
    return US_BOOK_DOMAINS


def allowed_search_results(results: Iterable[SearchResult], domains: Iterable[str]) -> list[SearchResult]:
    allowed = tuple(domain.lower().removeprefix("www.") for domain in domains)
    filtered: list[SearchResult] = []
    for result in results:
        merchant = merchant_from_url(result.url)
        host = urllib.parse.urlparse(result.url).netloc.lower().removeprefix("www.")
        if _is_non_book_retail_host(host):
            continue
        if merchant in allowed or any(host == domain or host.endswith(f".{domain}") for domain in allowed):
            if _is_search_or_category_url(result.url):
                continue
            filtered.append(result)
    return filtered


def _is_non_book_retail_host(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in NON_BOOK_RETAIL_HOSTS)


def extract_from_search_results(book: str, results: Iterable[SearchResult]) -> list[BookCandidate]:
    candidates: list[BookCandidate] = []
    for result in results:
        text = " ".join(part for part in (result.title, result.snippet) if part)
        candidates.extend(_extract_candidates(book, result.url, text, "search"))
    return candidates


def extract_from_fetched_pages(book: str, pages: Iterable[dict[str, Any]]) -> list[BookCandidate]:
    candidates: list[BookCandidate] = []
    for page in pages:
        text = page.get("text", "")
        if not isinstance(text, str):
            text = json.dumps(text)
        title = page.get("title") or ""
        url = page.get("final_url") or page.get("url") or ""
        candidates.extend(_extract_candidates(book, url, f"{title}\n{text}", "fetch"))
    return candidates


def _extract_candidates(book: str, url: str, text: str, source: str) -> list[BookCandidate]:
    merchant = merchant_from_url(url)
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    if merchant in SOCIAL_DOMAINS or _is_non_book_retail_host(host):
        return []
    if not _is_specific_listing_url(url):
        return []
    trust = trust_for_url(url)
    candidates: list[BookCandidate] = []
    for price_match in PRICE_RE.finditer(text):
        if _is_shipping_price(text, price_match.start(), price_match.end()):
            continue
        currency = price_match.group(1)
        price = _parse_money(price_match.group(2))
        if price is None or price < 0.5 or price > 500:
            continue

        evidence = _window(text, price_match.start(), price_match.end())
        if not _looks_like_book_listing(book, evidence):
            continue

        signal_window = _window(text, price_match.start(), price_match.end(), radius=80)
        shipping = _extract_shipping(signal_window)
        condition = _extract_condition(signal_window)
        flags = blocked_flags(evidence)
        candidates.append(
            BookCandidate(
                title=book,
                merchant=merchant,
                url=url,
                price=price,
                currency=currency,
                shipping=shipping,
                condition=condition,
                source=source,
                evidence=_squash(evidence),
                trust=trust,
                flags=flags,
            )
        )
    return candidates


def _is_specific_listing_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    merchant = merchant_from_url(url)
    path = parsed.path.rstrip("/")
    query = urllib.parse.parse_qs(parsed.query)

    if _is_search_or_category_url(url):
        return False

    if merchant in {"amazon.com", "amazon.co.uk"}:
        return bool(
            re.search(r"/(?:dp|gp/product|kindle-dbs/product)/[A-Z0-9]{10}(?:/|$)", path)
            or re.search(r"/[A-Z0-9]{10}(?:/|$)", path)
        )

    if merchant in {"ebay.com", "ebay.co.uk"}:
        return "/itm/" in path

    return bool(path and path != "/")


def _is_search_or_category_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    merchant = merchant_from_url(url)
    path = parsed.path.rstrip("/")
    query = urllib.parse.parse_qs(parsed.query)

    if merchant in {"amazon.com", "amazon.co.uk"}:
        return path in {"", "/", "/s"} or "k" in query

    blocked_path_parts = (
        "/search",
        "/search/",
        "/catalogsearch",
        "/collections",
        "/category",
        "/categories",
    )
    if any(part in path.lower() for part in blocked_path_parts):
        return True

    return False


def _parse_money(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _extract_shipping(text: str) -> float | None:
    lowered = text.lower()
    if "free shipping" in lowered or "free delivery" in lowered:
        return 0.0
    match = SHIPPING_RE.search(text)
    if match:
        return _parse_money(match.group(2))
    return None


def _is_shipping_price(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 4) : start]
    after = text[end : min(len(text), end + 20)].lower().lstrip()
    return before.strip().endswith("+") or after.startswith(("shipping", "delivery", "ship"))


def _extract_condition(text: str) -> str:
    lowered = text.lower()
    if "ebook" in lowered or "e-book" in lowered or "kindle" in lowered:
        return "ebook"
    for term in CONDITION_TERMS:
        if term in lowered:
            return term
    return "unknown"


def _looks_like_book_listing(book: str, evidence: str) -> bool:
    lowered = evidence.lower()
    book_terms = [term for term in re.findall(r"[a-z0-9]+", book.lower()) if len(term) > 2]
    has_book_hint = any(term in lowered for term in BOOK_MARKETPLACE_TERMS)
    has_title_hint = sum(1 for term in book_terms if term in lowered) >= max(1, min(2, len(book_terms)))
    bad_price_context = any(term in lowered for term in ("save $", "coupon", "cashback", "gift card"))
    return (has_book_hint or has_title_hint) and not bad_price_context


def _window(text: str, start: int, end: int, radius: int = 220) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:500]


def dedupe_candidates(candidates: Iterable[BookCandidate]) -> list[BookCandidate]:
    seen: dict[tuple[str, float, float | None, str], BookCandidate] = {}
    for candidate in candidates:
        key = (candidate.url, candidate.price, candidate.shipping, candidate.condition)
        current = seen.get(key)
        if current is None or (candidate.source == "fetch" and current.source == "search"):
            seen[key] = candidate
    return list(seen.values())


def _chunks(items: Iterable[str], size: int) -> Iterable[tuple[str, ...]]:
    group: list[str] = []
    for item in items:
        group.append(item)
        if len(group) == size:
            yield tuple(group)
            group = []
    if group:
        yield tuple(group)


def polite_pause(seconds: float = 12.5) -> None:
    # Handy if this grows into multiple searches. Free search allows 5 requests/minute.
    time.sleep(seconds)


def load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
