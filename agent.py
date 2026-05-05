from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

from rank import BookCandidate, blocked_flags, merchant_from_url, trust_for_url


SEARCH_ENDPOINT = "https://api.search.tinyfish.ai"
FETCH_ENDPOINT = "https://api.fetch.tinyfish.ai"

PRICE_RE = re.compile(r"(?<!\w)\$\s*([0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]{2})?)")
SHIPPING_RE = re.compile(
    r"(?:\+\s*)?\$\s*([0-9]{1,3}(?:\.[0-9]{2})?)\s*(?:shipping|delivery|ship)",
    re.IGNORECASE,
)
CONDITION_TERMS = (
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
    "book",
    "shipping",
    "condition",
    "seller",
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
    max_results: int = 8,
    fetch_pages: bool = True,
    location: str = "US",
    language: str = "en",
    client: TinyFishClient | None = None,
) -> list[BookCandidate]:
    client = client or TinyFishClient()
    query = build_search_query(book)
    results = client.search(query, location=location, language=language)
    candidates = extract_from_search_results(book, results[:max_results])

    if fetch_pages:
        # Search and fetch are free, but the free tier is rate limited. Fetch only the
        # most promising result URLs, in a single batch, so the CLI stays courteous.
        urls = [result.url for result in results[:max_results]]
        pages = client.fetch(urls)
        candidates.extend(extract_from_fetched_pages(book, pages))

    return dedupe_candidates(candidates)


def build_search_query(book: str) -> str:
    clean = " ".join(book.split())
    return f'"{clean}" book price used new shipping ThriftBooks AbeBooks Better World Books Target Walmart'


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
    trust = trust_for_url(url)
    candidates: list[BookCandidate] = []
    for price_match in PRICE_RE.finditer(text):
        if _is_shipping_price(text, price_match.start(), price_match.end()):
            continue
        price = _parse_money(price_match.group(1))
        if price is None or price < 0.5 or price > 500:
            continue

        evidence = _window(text, price_match.start(), price_match.end())
        if not _looks_like_book_listing(book, evidence):
            continue

        shipping = _extract_shipping(evidence)
        condition = _extract_condition(evidence)
        flags = blocked_flags(evidence)
        candidates.append(
            BookCandidate(
                title=book,
                merchant=merchant,
                url=url,
                price=price,
                shipping=shipping,
                condition=condition,
                source=source,
                evidence=_squash(evidence),
                trust=trust,
                flags=flags,
            )
        )
    return candidates


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
        return _parse_money(match.group(1))
    return None


def _is_shipping_price(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 4) : start]
    after = text[end : min(len(text), end + 20)].lower().lstrip()
    return before.strip().endswith("+") or after.startswith(("shipping", "delivery", "ship"))


def _extract_condition(text: str) -> str:
    lowered = text.lower()
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
